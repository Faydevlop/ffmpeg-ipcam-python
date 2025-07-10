import psutil
import subprocess
import os
import sys
import threading
import time
from datetime import datetime
import re
import logging
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
import queue
from pathlib import Path

# ------------------- S3 Configuration -------------------
# Configure these with AWS credentials and S3 bucket
AWS_ACCESS_KEY_ID = 'your-access-key-id'
AWS_SECRET_ACCESS_KEY = 'your-secret-access-key'
AWS_REGION = 'us-east-1'  # Change to your region
S3_BUCKET_NAME = 'your-bucket-name'
S3_FOLDER_PREFIX = 'recorded-videos/'  # Folder in S3 bucket

# ------------------- Logging Configuration -------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('video_recorder.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ------------------- S3 Upload Queue and Scheduler -------------------
class S3UploadScheduler:
    def __init__(self):
        self.upload_queue = queue.Queue()
        self.running = True
        self.upload_thread = None
        self.s3_client = None
        self.initialize_s3_client()
        
    def initialize_s3_client(self):
        """Initialize S3 client with credentials"""
        try:
            self.s3_client = boto3.client(
                's3',
                aws_access_key_id=AWS_ACCESS_KEY_ID,
                aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
                region_name=AWS_REGION
            )
            # Test connection
            self.s3_client.head_bucket(Bucket=S3_BUCKET_NAME)
            logger.info("S3 client initialized successfully")
        except NoCredentialsError:
            logger.error("AWS credentials not found. Please configure AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY")
            self.s3_client = None
        except ClientError as e:
            logger.error(f"Failed to initialize S3 client: {e}")
            self.s3_client = None
        except Exception as e:
            logger.error(f"Unexpected error initializing S3 client: {e}")
            self.s3_client = None
    
    def start_scheduler(self):
        """Start the upload scheduler thread"""
        if self.s3_client is None:
            logger.warning("S3 client not initialized. Upload scheduler will not start.")
            return
            
        self.upload_thread = threading.Thread(target=self._upload_worker, daemon=True)
        self.upload_thread.start()
        logger.info("S3 upload scheduler started")
    
    def stop_scheduler(self):
        """Stop the upload scheduler"""
        self.running = False
        if self.upload_thread:
            self.upload_thread.join(timeout=5)
        logger.info("S3 upload scheduler stopped")
    
    def queue_upload(self, file_path):
        """Add a file to the upload queue"""
        if self.s3_client is None:
            logger.warning(f"S3 client not available. Skipping upload for {file_path}")
            return
            
        if os.path.exists(file_path):
            self.upload_queue.put(file_path)
            logger.info(f"Queued for upload: {file_path}")
        else:
            logger.error(f"File not found for upload: {file_path}")
    
    def _upload_worker(self):
        """Worker thread that processes the upload queue"""
        while self.running:
            try:
                # Wait for a file to upload (with timeout to check if still running)
                file_path = self.upload_queue.get(timeout=1)
                self._upload_file(file_path)
                self.upload_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error in upload worker: {e}")
    
    def _upload_file(self, file_path):
        """Upload a single file to S3"""
        try:
            file_name = os.path.basename(file_path)
            s3_key = f"{S3_FOLDER_PREFIX}{file_name}"
            
            logger.info(f"Starting upload: {file_name}")
            
            # Upload with progress callback
            file_size = os.path.getsize(file_path)
            uploaded_bytes = 0
            
            def upload_callback(bytes_transferred):
                nonlocal uploaded_bytes
                uploaded_bytes += bytes_transferred
                progress = (uploaded_bytes / file_size) * 100
                if progress % 10 < 1:  # Log every 10% progress
                    logger.info(f"Upload progress for {file_name}: {progress:.1f}%")
            
            # Perform the upload
            self.s3_client.upload_file(
                file_path,
                S3_BUCKET_NAME,
                s3_key,
                Callback=upload_callback
            )
            
            logger.info(f"Upload success: {file_name} - {datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')}")
            
            # Delete local file after successful upload
            try:
                os.remove(file_path)
                logger.info(f"Local file deleted: {file_name}")
            except Exception as e:
                logger.error(f"Failed to delete local file {file_name}: {e}")
                
        except ClientError as e:
            logger.error(f"Upload failed: {file_name} - {e} - {datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')}")
        except Exception as e:
            logger.error(f"Upload failed: {file_name} - {e} - {datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')}")

# ------------------- Global Upload Scheduler -------------------
upload_scheduler = S3UploadScheduler()

# ------------------- Detect Removable Drives -------------------
def find_removable_drive():
    partitions = psutil.disk_partitions(all=False)
    for partition in partitions:
        if 'removable' in partition.opts.lower():
            return partition.mountpoint
    return None

# ------------------- Input Monitor Thread -------------------
def monitor_input(stop_event):
    while not stop_event.is_set():
        try:
            user_input = input().strip().lower()
            if user_input == 'stop':
                stop_event.set()
                break
        except EOFError:
            break

# ------------------- Get Available Cameras -------------------
def get_camera_list():
    try:
        print("Detecting available cameras...")
        result = subprocess.run(['ffmpeg', '-list_devices', 'true', '-f', 'dshow', '-i', 'dummy'], 
                              capture_output=True, text=True)
        output = result.stderr
        
        print("Raw FFmpeg output:")
        print("-" * 50)
        print(output)
        print("-" * 50)
        
        cameras = []
        lines = output.split('\n')
        
        # Look for video devices
        for line in lines:
            if '"' in line and ('video' in line.lower() or 'camera' in line.lower() or '(video)' in line):
                match = re.search(r'"([^"]+)".*\(video\)', line)
                if match:
                    camera_name = match.group(1)
                    if camera_name not in cameras:
                        cameras.append(camera_name)
        
        # If no cameras found with the above method, try alternative parsing
        if not cameras:
            for line in lines:
                if '"' in line and ('video' in line.lower() or 'camera' in line.lower()):
                    start = line.find('"') + 1
                    end = line.find('"', start)
                    if start > 0 and end > start:
                        camera_name = line[start:end]
                        if 'microphone' not in camera_name.lower() and 'audio' not in camera_name.lower():
                            if camera_name not in cameras:
                                cameras.append(camera_name)
        
        print(f"Detected cameras: {cameras}")
        return cameras
    except Exception as e:
        print(f"Error detecting cameras: {e}")
        return []

# ------------------- Test Camera Access -------------------
def test_camera_access(camera_name):
    print(f"Testing camera access: {camera_name}")
    try:
        test_commands = [
            [
                'ffmpeg',
                '-y',
                '-loglevel', 'warning',
                '-f', 'dshow',
                '-i', f'video={camera_name}',
                '-t', '2',
                '-f', 'null',
                '-'
            ],
            [
                'ffmpeg',
                '-y',
                '-loglevel', 'warning',
                '-f', 'dshow',
                '-i', f'video="{camera_name}"',
                '-t', '2',
                '-f', 'null',
                '-'
            ]
        ]
        
        for i, test_command in enumerate(test_commands):
            print(f"  Trying method {i+1}...")
            try:
                result = subprocess.run(test_command, capture_output=True, text=True, timeout=10)
                
                if result.returncode == 0:
                    print(f"✓ Camera '{camera_name}' is accessible with method {i+1}")
                    return True, i+1
                else:
                    print(f"  Method {i+1} failed: {result.stderr[:100]}...")
            except subprocess.TimeoutExpired:
                print(f"  Method {i+1} timed out")
            except Exception as e:
                print(f"  Method {i+1} error: {e}")
        
        print(f"✗ Camera '{camera_name}' is not accessible with any method")
        return False, 0
    except Exception as e:
        print(f"✗ Camera '{camera_name}' test error: {e}")
        return False, 0

# ------------------- Camera Selection -------------------
def select_camera():
    print("\n=== Camera Selection ===")
    print("1. Default camera (built-in/USB camera)")
    print("2. External IP webcam")
    
    while True:
        choice = input("Select camera (1 or 2): ").strip()
        
        if choice == '1':
            # Get available cameras
            cameras = get_camera_list()
            if cameras:
                print("\nAvailable cameras:")
                for i, cam in enumerate(cameras, 1):
                    print(f"  {i}. {cam}")
                
                while True:
                    try:
                        cam_choice = input(f"Select camera (1-{len(cameras)}) or press Enter for first camera: ").strip()
                        if not cam_choice:
                            selected_cam = cameras[0]
                        else:
                            cam_index = int(cam_choice) - 1
                            if 0 <= cam_index < len(cameras):
                                selected_cam = cameras[cam_index]
                            else:
                                print(f"Invalid choice. Please enter 1-{len(cameras)}")
                                continue
                        
                        # Test the selected camera
                        success, method = test_camera_access(selected_cam)
                        if success:
                            return selected_cam, method
                        else:
                            print("This camera is not accessible. Try another one.")
                            continue
                            
                    except ValueError:
                        print("Invalid input. Please enter a number.")
            else:
                print("No cameras detected automatically.")
                print("Please check your camera connections and try again.")
                return None, 0
                        
        elif choice == '2':
            ip_url = input("Enter IP webcam URL (or press Enter for default): ").strip()
            if not ip_url:
                ip_url = 'http://192.168.1.103:8080/video'
            return ip_url, 0
                
        else:
            print("Invalid choice. Please enter 1 or 2.")

# ------------------- Build FFmpeg Command -------------------
def build_ffmpeg_command(camera_info, output_path):
    camera_name, method = camera_info
    
    if isinstance(camera_name, str) and camera_name.startswith('http'):
        # IP webcam
        return [
            'ffmpeg',
            '-y',
            '-loglevel', 'warning',
            '-i', camera_name,
            '-vcodec', 'libx264',
            '-pix_fmt', 'yuv420p',
            '-f', 'mp4',
            output_path
        ]
    else:
        # Local camera - use the method that worked during testing
        if method == 1:
            input_param = f'video={camera_name}'
        elif method == 2:
            input_param = f'video="{camera_name}"'
        else:
            input_param = f'video={camera_name}'
        
        return [
            'ffmpeg',
            '-y',
            '-loglevel', 'warning',
            '-f', 'dshow',
            '-i', input_param,
            '-vcodec', 'libx264',
            '-pix_fmt', 'yuv420p',
            '-r', '30',
            '-s', '1280x720',
            '-f', 'mp4',
            output_path
        ]

# ------------------- Generate Filename with Start and End Time -------------------
def generate_filename(start_time, end_time=None):
    start_str = start_time.strftime("%Y-%m-%d_%I-%M-%S_%p")
    if end_time:
        end_str = end_time.strftime("%I-%M-%S_%p")
        return f"captured_video_{start_str}_to_{end_str}.mp4"
    else:
        return f"captured_video_{start_str}.mp4"

# ------------------- Main -------------------
def main():
    try:
        # Start the upload scheduler
        upload_scheduler.start_scheduler()
        
        usb_drive = find_removable_drive()
        if not usb_drive:
            print("No removable drive found. Insert a USB drive and try again.")
            sys.exit()

        # Create folder in USB: captured_videos/
        video_folder = os.path.join(usb_drive, 'captured_videos')
        os.makedirs(video_folder, exist_ok=True)

        # Camera selection at startup
        selected_camera = select_camera()
        if selected_camera[0] is None:
            print("No camera selected. Exiting.")
            sys.exit()

        camera_name, method = selected_camera

        if isinstance(camera_name, str) and not camera_name.startswith('http'):
            print(f"Selected camera: {camera_name} (method {method})")
        else:
            print(f"Selected camera: {'IP Webcam' if camera_name.startswith('http') else camera_name}")

        while True:
            action = input('\nType "start" to begin recording, "camera" to change camera, or "exit" to quit: ').strip().lower()

            if action == 'start':
                start_time = datetime.now()
                # Generate initial filename (will be updated with end time later)
                temp_filename = f"temp_recording_{start_time.strftime('%Y%m%d_%H%M%S')}.mp4"
                temp_output_path = os.path.join(video_folder, temp_filename)

                print(f"Starting recording at: {start_time.strftime('%Y-%m-%d %I:%M:%S %p')}")
                print(f"Temporary file: {temp_output_path}")

                # Build FFmpeg command
                command = build_ffmpeg_command(selected_camera, temp_output_path)

                print(f"FFmpeg command: {' '.join(command)}")

                try:
                    process = subprocess.Popen(command, stdin=subprocess.PIPE, 
                                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                except Exception as e:
                    print(f"Error starting FFmpeg: {e}")
                    continue

                print('Recording started. Type "stop" and press Enter to stop recording.')
                
                # Create a stop event for thread communication
                stop_event = threading.Event()
                
                # Start input monitoring thread
                input_thread = threading.Thread(target=monitor_input, args=(stop_event,))
                input_thread.daemon = True
                input_thread.start()

                # Wait for either process to finish or stop command
                recording_start_time = time.time()
                while process.poll() is None and not stop_event.is_set():
                    time.sleep(0.1)
                    # Check if process failed to start (exits immediately)
                    if time.time() - recording_start_time > 3 and process.poll() is not None:
                        print("FFmpeg process ended unexpectedly. Checking error...")
                        stderr_output = process.stderr.read().decode('utf-8', errors='ignore')
                        if stderr_output:
                            print(f"FFmpeg error: {stderr_output}")
                        break

                end_time = datetime.now()
                
                if stop_event.is_set():
                    # Send 'q' to FFmpeg for graceful shutdown
                    try:
                        process.stdin.write(b'q\n')
                        process.stdin.flush()
                        
                        # Wait for FFmpeg to finish gracefully (with timeout)
                        try:
                            process.wait(timeout=10)
                            print(f'Recording stopped at: {end_time.strftime("%Y-%m-%d %I:%M:%S %p")}')
                            
                            # Generate final filename with start and end time
                            final_filename = generate_filename(start_time, end_time)
                            final_output_path = os.path.join(video_folder, final_filename)
                            
                            # Rename the temporary file to final filename
                            if os.path.exists(temp_output_path):
                                os.rename(temp_output_path, final_output_path)
                                print(f'Recording saved as: {final_filename}')
                                
                                # Queue the file for S3 upload
                                upload_scheduler.queue_upload(final_output_path)
                                
                            else:
                                print('Recording file not found.')
                                
                        except subprocess.TimeoutExpired:
                            print('FFmpeg taking too long to stop, force terminating...')
                            process.terminate()
                            process.wait()
                            print('Recording force stopped. File may be corrupted.')
                            
                            # Still try to rename and upload if file exists
                            if os.path.exists(temp_output_path):
                                final_filename = generate_filename(start_time, end_time)
                                final_output_path = os.path.join(video_folder, final_filename)
                                os.rename(temp_output_path, final_output_path)
                                print(f'Recording saved as: {final_filename} (may be corrupted)')
                                upload_scheduler.queue_upload(final_output_path)
                            
                    except (BrokenPipeError, OSError):
                        # If stdin is closed, try terminate
                        process.terminate()
                        process.wait()
                        print('Recording stopped (process terminated).')
                        
                        # Still try to rename and upload if file exists
                        if os.path.exists(temp_output_path):
                            final_filename = generate_filename(start_time, end_time)
                            final_output_path = os.path.join(video_folder, final_filename)
                            os.rename(temp_output_path, final_output_path)
                            print(f'Recording saved as: {final_filename}')
                            upload_scheduler.queue_upload(final_output_path)
                else:
                    # Process finished naturally or with error
                    if process.returncode != 0:
                        stderr_output = process.stderr.read().decode('utf-8', errors='ignore')
                        print(f'Recording failed. Error: {stderr_output}')
                        # Clean up temp file if it exists
                        if os.path.exists(temp_output_path):
                            os.remove(temp_output_path)
                    else:
                        print('Recording finished.')
                        # Generate final filename and rename
                        if os.path.exists(temp_output_path):
                            final_filename = generate_filename(start_time, end_time)
                            final_output_path = os.path.join(video_folder, final_filename)
                            os.rename(temp_output_path, final_output_path)
                            print(f'Recording saved as: {final_filename}')
                            upload_scheduler.queue_upload(final_output_path)

            elif action == 'camera':
                selected_camera = select_camera()
                if selected_camera[0] is None:
                    print("No camera selected. Keeping current camera.")
                    continue
                camera_name, method = selected_camera
                if isinstance(camera_name, str) and not camera_name.startswith('http'):
                    print(f"Camera changed to: {camera_name} (method {method})")
                else:
                    print(f"Camera changed to: {'IP Webcam' if camera_name.startswith('http') else camera_name}")

            elif action == 'exit':
                print("Stopping upload scheduler...")
                upload_scheduler.stop_scheduler()
                print("Exiting...")
                sys.exit()

            else:
                print('Invalid command. Type "start" to record, "camera" to change camera, or "exit" to quit.')
    
    except KeyboardInterrupt:
        print("\nShutting down...")
        upload_scheduler.stop_scheduler()
        sys.exit()
    except Exception as e:
        logger.error(f"Unexpected error in main: {e}")
        upload_scheduler.stop_scheduler()
        sys.exit()

if __name__ == "__main__":
    main()