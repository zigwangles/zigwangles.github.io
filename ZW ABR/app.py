from flask import Flask, render_template, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from functools import wraps
import os

app = Flask(__name__, template_folder="templates")
app.config['SECRET_KEY'] = 'secretkey'  # Change this for production!
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///audiobook.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

################################################
# ADMIN-ONLY DECORATOR
################################################
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
         if not current_user.is_authenticated or current_user.username != "admin":
             flash("You must be an admin to access this page.")
             return redirect(url_for("login"))
         return f(*args, **kwargs)
    return decorated_function

################################################
# DATABASE MODELS
################################################
# Association tables for many-to-many relationships
book_category = db.Table(
    'book_category',
    db.Column('book_id', db.Integer, db.ForeignKey('book.id'), primary_key=True),
    db.Column('category_id', db.Integer, db.ForeignKey('category.id'), primary_key=True)
)

book_tag = db.Table(
    'book_tag',
    db.Column('book_id', db.Integer, db.ForeignKey('book.id'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id'), primary_key=True)
)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)  # Plain text—hash in production!
    saved_books = db.relationship('UserBook', backref='user', lazy=True)

class Book(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    author = db.Column(db.String(150), nullable=True)
    description = db.Column(db.Text, nullable=True)
    cover_image = db.Column(db.String(250), nullable=True)  # URL for cover art

    chapters = db.relationship('Chapter', backref='book', lazy=True)
    user_books = db.relationship('UserBook', back_populates='book')
    categories = db.relationship('Category', secondary=book_category, back_populates='books')

    # Remove the duplicate definition; keep just one
    tags = db.relationship(
        'Tag',
        secondary=book_tag,
        back_populates='books'
    )

class Chapter(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    book_id = db.Column(db.Integer, db.ForeignKey('book.id'), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    chapter_number = db.Column(db.Integer, nullable=True)
    audio_file = db.Column(db.String(250), nullable=False)  # URL for chapter audio
    
class UserBook(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    book_id = db.Column(db.Integer, db.ForeignKey('book.id'), nullable=False)
    status = db.Column(db.String(50), nullable=False, default='saved')
    current_position = db.Column(db.Float, default=0.0)  # <--- THIS
    current_chapter_id = db.Column(db.Integer, nullable=True)  # optional

    # ADD THIS RELATIONSHIP:
    book = db.relationship('Book', back_populates='user_books')

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    books = db.relationship('Book', secondary=book_category, back_populates='categories')

class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    book_id = db.Column(db.Integer, db.ForeignKey('book.id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)  # 1-5
    comment = db.Column(db.Text, nullable=True)

    user = db.relationship('User', backref='reviews')
    book = db.relationship('Book', backref='reviews')

class Tag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    # If you inadvertently added user_id, rating, comment here, remove them.
    books = db.relationship(
        'Book',
        secondary=book_tag,
        back_populates='tags'
    )
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

################################################
# ROUTES
################################################

@app.route('/')
def index():
    categories = Category.query.all()
    tags = Tag.query.all()
    return render_template('index.html', categories=categories, tags=tags)

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
         username = request.form.get('username')
         password = request.form.get('password')
         if User.query.filter_by(username=username).first():
              flash('Username already exists!')
              return redirect(url_for('signup'))
         new_user = User(username=username, password=password)
         db.session.add(new_user)
         db.session.commit()
         flash('Account created! Please log in.')
         return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/start_reading/<int:chapter_id>', methods=['GET'])
@login_required
def start_reading(chapter_id):
    # 1) Find the chapter
    chapter = Chapter.query.get_or_404(chapter_id)

    # 2) Find or create the user_book entry for the associated book
    ub = UserBook.query.filter_by(user_id=current_user.id, book_id=chapter.book_id).first()
    if not ub:
        ub = UserBook(user_id=current_user.id, book_id=chapter.book_id, status='currently_reading')
        db.session.add(ub)
    else:
        ub.status = 'currently_reading'

    # 3) Also store the current_chapter_id
    ub.current_chapter_id = chapter.id

    # (Optional) If you want only one book at a time:
    other_ubs = UserBook.query.filter_by(user_id=current_user.id, status='currently_reading').all()
    for other in other_ubs:
        if other.book_id != chapter.book_id:
            other.status = 'saved'

    db.session.commit()
    flash(f"You are now reading chapter {chapter.title}!")
    return redirect(url_for('book_detail', book_id=chapter.book_id))

@app.route('/save_later/<int:chapter_id>', methods=['GET'])
@login_required
def save_later(chapter_id):
    # We'll interpret "save for later" at the CHAPTER level,
    # though typically you'd do it at the book level. 
    chapter = Chapter.query.get_or_404(chapter_id)
    ub = UserBook.query.filter_by(user_id=current_user.id, book_id=chapter.book_id).first()
    if not ub:
        # Create user-book with 'saved'
        ub = UserBook(user_id=current_user.id, book_id=chapter.book_id, status='saved')
        db.session.add(ub)
    else:
        ub.status = 'saved'

    # Possibly set the current_chapter_id to this chapter
    ub.current_chapter_id = chapter.id
    db.session.commit()
    flash(f"Chapter {chapter.title} saved for later.")
    return redirect(url_for('book_detail', book_id=chapter.book_id))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
         username = request.form.get('username')
         password = request.form.get('password')
         user = User.query.filter_by(username=username, password=password).first()  # Plain text—hash in production!
         if user:
              login_user(user)
              return redirect(url_for('dashboard'))
         else:
              flash('Invalid credentials!')
              return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    user_books = UserBook.query.filter_by(user_id=current_user.id).all()

    for ub in user_books:
        if ub.current_chapter_id:
            # The user has a saved chapter
            ub.resume_chapter_id = ub.current_chapter_id
        else:
            # The user has no chapter set, so let's pick the first chapter in the book
            first_chapter = Chapter.query.filter_by(book_id=ub.book_id)\
                                         .order_by(Chapter.chapter_number.asc())\
                                         .first()
            if first_chapter:
                ub.resume_chapter_id = first_chapter.id
            else:
                ub.resume_chapter_id = None  # The book has no chapters

    saved = [ub for ub in user_books if ub.status == 'saved']
    current = [ub for ub in user_books if ub.status == 'currently_reading']
    finished = [ub for ub in user_books if ub.status == 'finished']

    return render_template('dashboard.html', saved=saved, current=current, finished=finished)
@app.route('/book/<int:book_id>')
def book_detail(book_id):
    book = Book.query.get_or_404(book_id)
    chapter = None
    chapter_id = request.args.get('chapter_id')
    if chapter_id:
        for ch in sorted(book.chapters, key=lambda x: x.chapter_number):
            if ch.id == int(chapter_id):
                chapter = ch
                break
    
    # If the user is logged in, find their UserBook record
    user_book = None
    if current_user.is_authenticated:
        user_book = UserBook.query.filter_by(user_id=current_user.id, book_id=book_id).first()

    return render_template('book_detail.html', book=book, chapter=chapter, user_book=user_book)
@app.route('/save_book/<int:book_id>')
@login_required
def save_book(book_id):
    existing = UserBook.query.filter_by(user_id=current_user.id, book_id=book_id).first()
    if not existing:
         new_entry = UserBook(user_id=current_user.id, book_id=book_id, status='saved')
         db.session.add(new_entry)
         db.session.commit()
         flash('Book saved for later!')
    else:
         flash('Book already saved or in progress.')
    return redirect(url_for('dashboard'))

@app.route('/start_book/<int:book_id>')
@login_required
def start_book(book_id):
    current_reading = UserBook.query.filter_by(user_id=current_user.id, status='currently_reading').first()
    if current_reading and current_reading.book_id != book_id:
         current_reading.status = 'saved'
    entry = UserBook.query.filter_by(user_id=current_user.id, book_id=book_id).first()
    if not entry:
         entry = UserBook(user_id=current_user.id, book_id=book_id, status='currently_reading')
         db.session.add(entry)
    else:
         entry.status = 'currently_reading'
    db.session.commit()
    flash('Enjoy your audiobook!')
    return redirect(url_for('dashboard'))


@app.route('/update_position/<int:book_id>', methods=['POST'])
@login_required
def update_position(book_id):
    user_book = UserBook.query.filter_by(user_id=current_user.id, book_id=book_id).first()
    if not user_book:
        return {"error": "No UserBook record found"}, 404
    
    new_position = request.form.get('position', type=float)
    if new_position is None:
        return {"error": "No position provided"}, 400
    
    user_book.current_position = new_position
    db.session.commit()
    return {"message": "Position updated", "position": user_book.current_position}, 200
    
    new_position = request.form.get('position', type=float)
    if new_position is None:
        return {"error": "No position provided"}, 400
    
    user_book.current_position = new_position
    db.session.commit()
    return {"message": "Position updated", "position": user_book.current_position}, 200

@app.route('/finish_book/<int:book_id>')
@login_required
def finish_book(book_id):
    ub = UserBook.query.filter_by(user_id=current_user.id, book_id=book_id).first()
    if ub:
        ub.status = 'finished'
        db.session.commit()
        flash("Book finished!")
    return redirect(url_for('dashboard'))

@app.route('/add_review/<int:book_id>', methods=['GET', 'POST'])
@login_required
def add_review(book_id):
    book = Book.query.get_or_404(book_id)

    if request.method == 'POST':
        # get data from form
        rating = request.form.get('rating', type=int)
        comment = request.form.get('comment', '')

        # check if user already reviewed this book
        existing = Review.query.filter_by(user_id=current_user.id, book_id=book_id).first()
        if existing:
            flash("You already reviewed this book. Edit your previous review instead.")
            return redirect(url_for('book_detail', book_id=book_id))
        
        # create new review record
        new_review = Review(
            user_id=current_user.id,
            book_id=book_id,
            rating=rating,
            comment=comment
        )
        db.session.add(new_review)
        db.session.commit()

        flash("Thanks for your review!")
        return redirect(url_for('book_detail', book_id=book_id))
    
    # If GET request, just show the form
    return render_template('add_review.html', book=book)

################################################
# ADMIN-ONLY BOOK MANAGEMENT ROUTES
################################################
@app.route('/add_book', methods=['GET', 'POST'])
@login_required
@admin_required
def add_book():
    if request.method == 'POST':
         title = request.form.get('title')
         author = request.form.get('author')
         description = request.form.get('description')
         cover_image = request.form.get('cover_image')
         new_book = Book(title=title, author=author, description=description, cover_image=cover_image)
         db.session.add(new_book)
         db.session.commit()
         flash('Book added successfully!')
         return redirect(url_for('index'))
    return render_template('add_book.html')

@app.route('/edit_book/<int:book_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_book(book_id):
    book = Book.query.get_or_404(book_id)
    all_categories = Category.query.all()
    all_tags = Tag.query.all()
    if request.method == 'POST':
        book.title = request.form.get('title')
        book.author = request.form.get('author')
        book.description = request.form.get('description')
        book.cover_image = request.form.get('cover_image')
        # Update categories from checkboxes/multi-select
        selected_cat_ids = request.form.getlist('categories')
        new_categories = Category.query.filter(Category.id.in_(selected_cat_ids)).all()
        book.categories = new_categories
        # Update tags from checkboxes/multi-select
        selected_tag_ids = request.form.getlist('tags')
        new_tags = Tag.query.filter(Tag.id.in_(selected_tag_ids)).all()
        book.tags = new_tags
        db.session.commit()
        flash('Book updated successfully!')
        return redirect(url_for('book_detail', book_id=book.id))
    return render_template('edit_book.html', book=book, all_categories=all_categories, all_tags=all_tags)

@app.route('/delete_book/<int:book_id>', methods=['POST'])
@login_required
@admin_required
def delete_book(book_id):
    book = Book.query.get_or_404(book_id)
    
    # 1) Delete all user_book rows that reference this book
    user_books = UserBook.query.filter_by(book_id=book_id).all()
    for ub in user_books:
        db.session.delete(ub)
    
    # 2) Delete all chapters for this book (if not already set to cascade)
    for ch in book.chapters:
        db.session.delete(ch)
    
    # 3) Now delete the book itself
    db.session.delete(book)
    db.session.commit()
    
    flash('Book and all references to it have been deleted successfully!')
    return redirect(url_for('index'))

@app.route('/add_chapter/<int:book_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def add_chapter(book_id):
    book = Book.query.get_or_404(book_id)
    if request.method == 'POST':
         title = request.form.get('title')
         chapter_number = request.form.get('chapter_number')
         audio_file = request.form.get('audio_file')
         chapter_number = int(chapter_number) if chapter_number else None
         new_chapter = Chapter(book_id=book.id, title=title, chapter_number=chapter_number, audio_file=audio_file)
         db.session.add(new_chapter)
         db.session.commit()
         flash("Chapter added successfully!")
         return redirect(url_for('book_detail', book_id=book.id))
    return render_template('add_chapter.html', book=book)

################################################
# ADMIN-ONLY MANAGE BOOKS SECTION (Edit Books & Edit Tags)
################################################
@app.route('/manage_books')
@login_required
@admin_required
def manage_books():
    books = Book.query.all()
    tags = Tag.query.all()
    return render_template('manage_books.html', books=books, tags=tags)

# Route to assign books to a tag (to change the number of books under a tag)
@app.route('/assign_tag/<int:tag_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def assign_tag(tag_id):
    tag = Tag.query.get_or_404(tag_id)
    books = Book.query.all()
    if request.method == 'POST':
        selected_book_ids = request.form.getlist('books')
        selected_books = Book.query.filter(Book.id.in_(selected_book_ids)).all()
        tag.books = selected_books
        db.session.commit()
        flash("Tag assignments updated!")
        return redirect(url_for('manage_books'))
    return render_template('assign_tag.html', tag=tag, books=books)

################################################
# ADMIN-ONLY CATEGORIES ROUTES
################################################
@app.route('/categories')
@login_required
@admin_required
def list_categories():
    categories = Category.query.all()
    return render_template('categories/list.html', categories=categories)

@app.route('/categories/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_category():
    if request.method == 'POST':
        name = request.form.get('name')
        if Category.query.filter_by(name=name).first():
            flash("Category already exists!")
            return redirect(url_for('add_category'))
        new_cat = Category(name=name)
        db.session.add(new_cat)
        db.session.commit()
        flash("Category added!")
        return redirect(url_for('list_categories'))
    return render_template('categories/add.html')

@app.route('/categories/edit/<int:cat_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_category(cat_id):
    cat = Category.query.get_or_404(cat_id)
    if request.method == 'POST':
        name = request.form.get('name')
        if (name != cat.name) and Category.query.filter_by(name=name).first():
            flash("Category name already in use!")
            return redirect(url_for('edit_category', cat_id=cat.id))
        cat.name = name
        db.session.commit()
        flash("Category updated!")
        return redirect(url_for('list_categories'))
    return render_template('categories/edit.html', category=cat)

@app.route('/categories/delete/<int:cat_id>', methods=['POST'])
@login_required
@admin_required
def delete_category(cat_id):
    cat = Category.query.get_or_404(cat_id)
    db.session.delete(cat)
    db.session.commit()
    flash("Category deleted!")
    return redirect(url_for('list_categories'))

@app.route('/tag/<int:tag_id>')
def tag_detail(tag_id):
    tag = Tag.query.get_or_404(tag_id)
    return render_template('tag_detail.html', tag=tag)

################################################
# ADMIN-ONLY TAGS ROUTES
################################################
@app.route('/tags')
@login_required
@admin_required
def list_tags():
    tags = Tag.query.all()
    return render_template('tags/list.html', tags=tags)

@app.route('/tags/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_tag():
    if request.method == 'POST':
        name = request.form.get('name')
        if Tag.query.filter_by(name=name).first():
            flash("Tag already exists!")
            return redirect(url_for('add_tag'))
        new_tag = Tag(name=name)
        db.session.add(new_tag)
        db.session.commit()
        flash("Tag added!")
        return redirect(url_for('list_tags'))
    return render_template('tags/add.html')

@app.route('/tags/edit/<int:tag_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_tag(tag_id):
    tag = Tag.query.get_or_404(tag_id)
    if request.method == 'POST':
        name = request.form.get('name')
        if (name != tag.name) and Tag.query.filter_by(name=name).first():
            flash("Tag name already in use!")
            return redirect(url_for('edit_tag', tag_id=tag.id))
        tag.name = name
        db.session.commit()
        flash("Tag updated!")
        return redirect(url_for('list_tags'))
    return render_template('tags/edit.html', tag=tag)

@app.route('/tags/delete/<int:tag_id>', methods=['POST'])
@login_required
@admin_required
def delete_tag(tag_id):
    tag = Tag.query.get_or_404(tag_id)
    db.session.delete(tag)
    db.session.commit()
    flash("Tag deleted!")
    return redirect(url_for('list_tags'))

@app.route('/admin_dashboard')
@login_required
@admin_required
def admin_dashboard():
    return render_template('admin_dashboard.html')

@app.route('/choose_book_for_chapter', methods=['GET', 'POST'])
@login_required
@admin_required
def choose_book_for_chapter():
    books = Book.query.all()
    if request.method == 'POST':
        selected_book_id = request.form.get('book_id')
        if selected_book_id:
            return redirect(url_for('add_chapter', book_id=selected_book_id))
        flash("Please select a book.")
    return render_template('choose_book_for_chapter.html', books=books)

################################################
# RUN THE APP
################################################
@app.context_processor
def inject_tags():
    # We'll query all tags so we can show them in the nav
    tags = Tag.query.all()
    return dict(nav_tags=tags)

if __name__ == '__main__':
    with app.app_context():
        if not os.path.exists('audiobook.db'):
            db.create_all()
            # Create the admin account if it doesn't exist
            if not User.query.filter_by(username="admin").first():
                admin_user = User(username="admin", password="Tr1ckSh0ts")
                db.session.add(admin_user)
                db.session.commit()
    app.run(debug=True)