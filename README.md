# Video Recorder with S3 Upload

A Python application that records videos from local cameras or IP webcams, saves them to a USB drive, and automatically uploads them to AWS S3 storage.

## Features

- **Multi-camera support**: Works with built-in cameras, USB cameras, and IP webcams
- **Automatic camera detection**: Scans and lists available video devices
- **USB storage**: Saves recordings to removable USB drives
- **AWS S3 integration**: Automatic upload to S3 with progress tracking
- **Background uploading**: Non-blocking S3 uploads using threaded queue system
- **Flexible file naming**: Timestamps with start and end times
- **Real-time control**: Start/stop recording with keyboard commands
- **Error handling**: Comprehensive logging and error recovery
- **Local cleanup**: Automatically deletes local files after successful upload

## Requirements

### System Dependencies
- **FFmpeg**: Required for video recording and encoding
  - Windows: Download from [https://ffmpeg.org/download.html](https://ffmpeg.org/download.html)
  - Add FFmpeg to your system PATH
- **Python 3.6+**
- **USB Drive**: For local video storage

### Python Dependencies
```bash
pip install psutil boto3
```

## Installation

1. **Clone or download** this repository
2. **Install FFmpeg** and ensure it's in your system PATH
3. **Install Python dependencies**:
   ```bash
   pip install psutil boto3
   ```
4. **Configure AWS credentials** (see Configuration section)

## Configuration

### AWS S3 Setup
Edit the following variables in the script:

```python
AWS_ACCESS_KEY_ID = 'your-access-key-id'
AWS_SECRET_ACCESS_KEY = 'your-secret-access-key'
AWS_REGION = 'us-east-1'  # Change to your region
S3_BUCKET_NAME = 'your-bucket-name'
S3_FOLDER_PREFIX = 'recorded-videos/'  # Folder in S3 bucket
```

### AWS Credentials
You can also set AWS credentials using:
- Environment variables (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`)
- AWS credentials file (`~/.aws/credentials`)
- IAM roles (if running on EC2)

### Required S3 Permissions
Your AWS user/role needs the following S3 permissions:
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:PutObject",
                "s3:GetObject",
                "s3:DeleteObject"
            ],
            "Resource": "arn:aws:s3:::your-bucket-name/*"
        },
        {
            "Effect": "Allow",
            "Action": "s3:ListBucket",
            "Resource": "arn:aws:s3:::your-bucket-name"
        }
    ]
}
```

## Usage

### Starting the Application
```bash
python video_recorder.py
```

### Basic Workflow
1. **Insert USB drive** - The app will detect removable drives automatically
2. **Select camera** - Choose from detected cameras or enter IP webcam URL
3. **Start recording** - Type `start` and press Enter
4. **Stop recording** - Type `stop` and press Enter
5. **Automatic upload** - Videos are queued for S3 upload and local files are cleaned up

### Available Commands
- `start` - Begin video recording
- `stop` - Stop current recording (while recording is active)
- `camera` - Change camera source
- `exit` - Quit the application

### Camera Options
1. **Local cameras**: Automatically detected USB/built-in cameras
2. **IP webcams**: Enter URL (e.g., `http://192.168.1.103:8080/video`)

## File Structure

```
USB Drive/
└── captured_videos/
    ├── captured_video_2024-01-15_02-30-45_PM_to_02-45-30_PM.mp4
    ├── captured_video_2024-01-15_03-15-20_PM_to_03-25-10_PM.mp4
    └── ...
```

## Output Format

- **Video codec**: H.264 (libx264)
- **Container**: MP4
- **Resolution**: 1280x720 (for local cameras)
- **Frame rate**: 30 fps
- **Pixel format**: yuv420p (widely compatible)

## Logging

The application creates detailed logs in `video_recorder.log` including:
- Camera detection and testing
- Recording start/stop times
- S3 upload progress and status
- Error messages and debugging information

## Troubleshooting

### Common Issues

**No cameras detected**
- Ensure cameras are connected and not in use by other applications
- Check Windows privacy settings for camera access
- Verify FFmpeg is installed and in PATH

**S3 upload failures**
- Verify AWS credentials are correct
- Check internet connectivity
- Ensure S3 bucket exists and is accessible
- Verify IAM permissions

**Recording fails to start**
- Try different camera selection methods
- Check if camera is being used by another application
- Verify FFmpeg installation with `ffmpeg -version`

**USB drive not detected**
- Ensure drive is formatted and mounted
- Try different USB ports
- Check if drive appears in File Explorer

### Debug Mode
For additional debugging, you can modify the logging level:
```python
logging.basicConfig(level=logging.DEBUG, ...)
```

## Technical Details

### Architecture
- **Main thread**: User interface and recording control
- **Upload thread**: Background S3 uploads with queue system
- **Input monitoring thread**: Non-blocking keyboard input detection

### Video Recording Process
1. FFmpeg process spawned with appropriate parameters
2. Recording continues until user stops or process fails
3. Graceful shutdown with 'q' command to FFmpeg
4. File renamed with start/end timestamps
5. Queued for S3 upload and local cleanup

### S3 Upload Process
1. Files added to thread-safe upload queue
2. Background worker processes uploads sequentially
3. Progress tracking with callback functions
4. Automatic local file deletion after successful upload
5. Comprehensive error handling and retry logic

## Security Considerations

- Store AWS credentials securely (consider using environment variables)
- Use IAM roles with minimal required permissions
- Ensure S3 bucket has appropriate access policies
- Consider encrypting sensitive recordings

## License

This project is provided as-is for educational and personal use. Please ensure compliance with local laws regarding video recording and data storage.

## Contributing

Feel free to submit issues, feature requests, or pull requests to improve this application.

## Support

For issues related to:
- **FFmpeg**: Check FFmpeg documentation and community forums
- **AWS S3**: Consult AWS documentation and support
- **Camera compatibility**: Test with different cameras and report issues
