// Get DOM elements
const videoFile = document.getElementById('videoFile');
const videoPlayer = document.getElementById('videoPlayer');
const timestamps = document.getElementById('timestamps');
const processButton = document.getElementById('processButton');
const clipsList = document.getElementById('clipsList');

let videoBlob = null;

// Handle video file upload
videoFile.addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (file) {
        videoBlob = file;
        videoPlayer.src = URL.createObjectURL(file);
        processButton.disabled = false;
    }
});

// Convert timestamp string to seconds
function parseTimestamp(timestamp) {
    const [hours, minutes, seconds] = timestamp.split(':').map(Number);
    return hours * 3600 + minutes * 60 + seconds;
}

// Convert seconds to timestamp format
function formatTime(seconds) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

// Process button click handler
processButton.addEventListener('click', () => {
    const timestampLines = timestamps.value.trim().split('\n');
    clipsList.innerHTML = '';

    timestampLines.forEach((line, index) => {
        const [start, end] = line.split('-').map(t => parseTimestamp(t.trim()));
        createClip(start, end, index);
    });
});

// Create clip elements with download functionality
function createClip(start, end, index) {
    const clipItem = document.createElement('div');
    clipItem.className = 'clip-item';
    
    const timeLabel = document.createElement('span');
    timeLabel.textContent = `Clip ${index + 1}: ${formatTime(start)} - ${formatTime(end)}`;
    
    const downloadButton = document.createElement('button');
    downloadButton.textContent = 'Download Clip';
    downloadButton.addEventListener('click', async () => {
        try {
            const originalVideo = document.createElement('video');
            originalVideo.src = URL.createObjectURL(videoBlob);
            
            await new Promise(resolve => {
                originalVideo.addEventListener('loadedmetadata', () => {
                    // Create virtual video element
                    const clipVideo = document.createElement('video');
                    clipVideo.src = originalVideo.src;
                    
                    // Set the starting point
                    clipVideo.currentTime = start;
                    
                    // Create canvas for video processing
                    const canvas = document.createElement('canvas');
                    canvas.width = originalVideo.videoWidth;
                    canvas.height = originalVideo.videoHeight;
                    const ctx = canvas.getContext('2d');
                    
                    // Set up MediaRecorder
                    const stream = canvas.captureStream();
                    const mediaRecorder = new MediaRecorder(stream, {
                        mimeType: 'video/webm;codecs=vp8,opus'
                    });
                    
                    const chunks = [];
                    
                    mediaRecorder.ondataavailable = (e) => chunks.push(e.data);
                    mediaRecorder.onstop = () => {
                        const blob = new Blob(chunks, { type: 'video/webm' });
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement('a');
                        a.href = url;
                        a.download = `clip_${index + 1}.webm`;
                        document.body.appendChild(a);
                        a.click();
                        document.body.removeChild(a);
                        URL.revokeObjectURL(url);
                    };
                    
                    // Start recording
                    mediaRecorder.start(100);
                    clipVideo.play();
                    
                    // Process video frames
                    function drawFrame() {
                        if (clipVideo.currentTime >= end) {
                            clipVideo.pause();
                            mediaRecorder.stop();
                            return;
                        }
                        ctx.drawImage(clipVideo, 0, 0, canvas.width, canvas.height);
                        requestAnimationFrame(drawFrame);
                    }
                    
                    drawFrame();
                    resolve();
                });
            });
        } catch (error) {
            console.error('Error processing video:', error);
            alert('Error processing video. Please try again.');
        }
    });

    clipItem.appendChild(timeLabel);
    clipItem.appendChild(downloadButton);
    clipsList.appendChild(clipItem);
}