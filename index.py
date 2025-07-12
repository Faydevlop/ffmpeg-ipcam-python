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
import webbrowser
import socket
from http.server import HTTPServer, BaseHTTPRequestHandler
import select

active_live_servers = []

# ------------------- S3 Configuration -------------------
AWS_ACCESS_KEY_ID = ''
AWS_SECRET_ACCESS_KEY = ''
AWS_REGION = 'eu-north-1'
S3_BUCKET_NAME = 'my-bucket-save'
S3_FOLDER_PREFIX = 'recorded-videos/'

# ------------------- Integrated Devices -------------------
INTEGRATED_DEVICES = [
    {"name": "Camera 1", "ip": "http://192.168.1.103:8080/video"},
    {"name": "Camera 2", "ip": "http://193.163.12.1:8080/video"},
    {"name": "Fayis Phone", "ip": "http://192.168.1.103:8080/video"}
]

# ------------------- Logging Configuration -------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('video_recorder.log')
        # Removed StreamHandler to prevent terminal output
    ]
)
logger = logging.getLogger(__name__)

# ------------------- Live Stream Server -------------------
class LiveStreamHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            if not hasattr(self.server, 'is_active') or not self.server.is_active:
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(b"""
                <!DOCTYPE html>
                <html><body style="text-align:center; font-family:Arial; padding:50px;">
                <h1>Live Stream Stopped</h1>
                <p>The live stream has been stopped. You can close this tab.</p>
                <script>setTimeout(function(){window.close();}, 3000);</script>
                </body>
                </html>
                """)
                return
            
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Live IP Camera Feed</title>
                <style>
                    body {{
                        font-family: Arial, sans-serif;
                        text-align: center;
                        background-color: #f0f0f0;
                        margin: 0;
                        padding: 20px;
                    }}
                    .container {{
                        max-width: 1200px;
                        margin: 0 auto;
                        background-color: white;
                        padding: 20px;
                        border-radius: 10px;
                        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
                    }}
                    h1 {{
                        color: #333;
                        margin-bottom: 20px;
                    }}
                    .video-container {{
                        margin: 20px 0;
                        border: 2px solid #ddd;
                        border-radius: 8px;
                        overflow: hidden;
                        display: inline-block;
                    }}
                    img {{
                        max-width: 100%;
                        height: auto;
                        display: block;
                    }}
                    .info {{
                        background-color: #e8f4f8;
                        padding: 15px;
                        border-radius: 5px;
                        margin: 20px 0;
                        color: #2c3e50;
                    }}
                    .status {{
                        font-size: 18px;
                        font-weight: bold;
                        color: #27ae60;
                        margin: 10px 0;
                    }}
                    .controls {{
                        margin: 20px 0;
                        font-size: 16px;
                        color: #7f8c8d;
                    }}
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>🎥 Live IP Camera Feed</h1>
                    <div class="status">● Live Stream Active (Video Only)</div>
                    
                    <div class="video-container">
                        <img src="{self.server.camera_url}" alt="Live Camera Feed" id="cameraFeed">
                    </div>
                    
                    <div class="info">
                        <strong>Camera URL:</strong> {self.server.camera_url}<br>
                        <strong>Stream Started:</strong> {self.server.start_time}
                    </div>
                    
                    <div class="controls">
                        <p>To stop the live stream, type <strong>"stop"</strong> in the console and press Enter.</p>
                    </div>
                </div>
                
                <script>
                    setInterval(function() {{
                        fetch(window.location.href)
                            .then(response => response.text())
                            .then(html => {{
                                if (html.includes('Live Stream Stopped')) {{
                                    window.location.reload();
                                }}
                            }})
                            .catch(() => {{
                                window.location.reload();
                            }});
                        var img = document.getElementById('cameraFeed');
                        var timestamp = new Date().getTime();
                        img.src = img.src.split('?')[0] + '?t=' + timestamp;
                    }}, 10000);
                    document.getElementById('cameraFeed').onerror = function() {{
                        this.alt = 'Camera feed unavailable - Check camera connection';
                        this.style.backgroundColor = '#f8d7da';
                        this.style.color = '#721c24';
                        this.style.padding = '50px';
                        this.style.border = '2px solid #f5c6cb';
                    }};
                </script>
            </body>
            </html>
            """
            self.wfile.write(html_content.encode())
        else:
            self.send_error(404)
    
    def log_message(self, format, *args):
        pass

class LiveStreamServer:
    def __init__(self, camera_url, port=8000):
        self.camera_url = camera_url
        self.port = port
        self.server = None
        self.server_thread = None
        self.start_time = datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')
        
    def find_free_port(self):
        port = self.port
        while port < self.port + 100:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(('localhost', port))
                    return port
            except OSError:
                port += 1
        return None
    
    def start_server(self):
        try:
            free_port = self.find_free_port()
            if free_port is None:
                print("Could not find a free port for live stream server")
                return None
            
            self.port = free_port
            self.server = HTTPServer(('localhost', self.port), LiveStreamHandler)
            self.server.camera_url = self.camera_url
            self.server.start_time = self.start_time
            self.server.is_active = True
            
            self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.server_thread.start()
            
            live_url = f"http://localhost:{self.port}"
            print(f"Live stream server started at: {live_url}")
            return live_url
            
        except Exception as e:
            print(f"Error starting live stream server: {e}")
            return None
    
    def stop_server(self):
        if self.server:
            self.server.is_active = False
            time.sleep(0.5)
            self.server.shutdown()
            self.server.server_close()
            print("Live stream server stopped")

# ------------------- S3 Upload Queue and Scheduler -------------------
class S3UploadScheduler:
    def __init__(self):
        self.upload_queue = queue.Queue()
        self.running = True
        self.upload_thread = None
        self.s3_client = None
        self.initialize_s3_client()
        self.is_active = True
        
    def initialize_s3_client(self):
        try:
            self.s3_client = boto3.client(
                's3',
                aws_access_key_id=AWS_ACCESS_KEY_ID,
                aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
                region_name=AWS_REGION
            )
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
        if self.s3_client is None:
            logger.warning("S3 client not initialized. Upload scheduler will not start.")
            return
        self.upload_thread = threading.Thread(target=self._upload_worker, daemon=True)
        self.upload_thread.start()
        logger.info("S3 upload scheduler started")
    
    def stop_scheduler(self):
        self.running = False
        if self.upload_thread:
            self.upload_thread.join(timeout=5)
        logger.info("S3 upload scheduler stopped")
    
    def queue_upload(self, file_path):
        if self.s3_client is None:
            logger.warning(f"S3 client not available. Skipping upload for {file_path}")
            return
        if os.path.exists(file_path):
            self.upload_queue.put(file_path)
            logger.info(f"Queued for upload: {file_path}")
        else:
            logger.error(f"File not found for upload: {file_path}")
    
    def check_file_exists_in_s3(self, file_name):
        """Check if a file exists in the S3 bucket"""
        if self.s3_client is None:
            return False
        try:
            s3_key = f"{S3_FOLDER_PREFIX}{file_name}"
            self.s3_client.head_object(Bucket=S3_BUCKET_NAME, Key=s3_key)
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                return False
            logger.error(f"Error checking file existence in S3 for {file_name}: {e}")
            return False
    
    def _upload_worker(self):
        """Worker thread that processes the upload queue"""
        while self.running:
            try:
                # Wait for a file to upload with timeout
                file_path = self.upload_queue.get(timeout=1)
                if file_path:
                    self._upload_file(file_path)
                    self.upload_queue.task_done()
            except queue.Empty:
                # Timeout occurred, continue checking if we should stop
                continue
            except Exception as e:
                logger.error(f"Error in upload worker: {e}")
                continue
    
    def _upload_file(self, file_path):
        try:
            file_name = os.path.basename(file_path)
            s3_key = f"{S3_FOLDER_PREFIX}{file_name}"
            logger.info(f"Starting upload: {file_name}")
            file_size = os.path.getsize(file_path)
            uploaded_bytes = 0
            
            def upload_callback(bytes_transferred):
                nonlocal uploaded_bytes
                uploaded_bytes += bytes_transferred
                progress = (uploaded_bytes / file_size) * 100
                if progress % 10 < 1:
                    logger.info(f"Upload progress for {file_name}: {progress:.1f}%")
            
            self.s3_client.upload_file(
                file_path,
                S3_BUCKET_NAME,
                s3_key,
                Callback=upload_callback
            )
            logger.info(f"Upload success: {file_name} - {datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')}")
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
            try:
                # Test write access
                test_file = os.path.join(partition.mountpoint, 'test_write.txt')
                with open(test_file, 'w') as f:
                    f.write('test')
                os.remove(test_file)
                return partition.mountpoint
            except (OSError, PermissionError) as e:
                logger.error(f"Cannot write to drive {partition.mountpoint}: {e}")
                continue
    return None

# ------------------- Input Monitor Thread -------------------
def monitor_input(stop_event):
    while not stop_event.is_set():
        try:
            if sys.platform.startswith('win'):
                import msvcrt
                while not stop_event.is_set():
                    if msvcrt.kbhit():
                        user_input = input().strip().lower()
                        if user_input == 'stop':
                            stop_event.set()
                            break
                    time.sleep(0.05)
            else:
                while not stop_event.is_set():
                    if select.select([sys.stdin], [], [], 0.05)[0]:
                        user_input = input().strip().lower()
                        if user_input == 'stop':
                            stop_event.set()
                            break
        except EOFError:
            break
        except KeyboardInterrupt:
            stop_event.set()
            break
        except Exception as e:
            logger.error(f"Error in input monitor: {e}")
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
        for line in lines:
            if '"' in line and ('video' in line.lower() or 'camera' in line.lower() or '(video)' in line):
                match = re.search(r'"([^"]+)".*\(video\)', line)
                if match:
                    camera_name = match.group(1)
                    if camera_name not in cameras:
                        cameras.append(camera_name)
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

# ------------------- Test Audio Stream -------------------
def test_audio_stream(audio_url):
    print(f"Testing audio stream: {audio_url}")
    test_file = 'test_audio.opus'
    test_command = [
        'ffmpeg',
        '-y',
        '-loglevel', 'info',
        '-re',
        '-reconnect', '1',
        '-reconnect_streamed', '1',
        '-reconnect_delay_max', '5',
        '-i', audio_url,
        '-t', '5',
        '-c:a', 'copy',
        test_file
    ]
    try:
        result = subprocess.run(test_command, capture_output=True, text=True, timeout=15)
        if result.returncode == 0 and os.path.exists(test_file) and os.path.getsize(test_file) > 0:
            print(f"✓ Audio stream '{audio_url}' is accessible")
            try:
                os.remove(test_file)
            except:
                pass
            return True
        else:
            print(f"✗ Audio stream '{audio_url}' test failed: {result.stderr[:200]}...")
            return False
    except subprocess.TimeoutExpired:
        print(f"✗ Audio stream '{audio_url}' test timed out")
        return False
    except Exception as e:
        print(f"✗ Audio stream '{audio_url}' test error: {e}")
        return False

# ------------------- Test Video Stream -------------------
def test_video_stream(video_url):
    print(f"Testing video stream: {video_url}")
    test_file = 'test_video.mjpeg'
    test_command = [
        'ffmpeg',
        '-y',
        '-loglevel', 'info',
        '-re',
        '-reconnect', '1',
        '-reconnect_streamed', '1',
        '-reconnect_on_network_error', '1',
        '-reconnect_delay_max', '5',
        '-timeout', '5000000',
        '-f', 'mpjpeg',
        '-i', video_url,
        '-t', '5',
        '-c:v', 'copy',
        test_file
    ]
    try:
        result = subprocess.run(test_command, capture_output=True, text=True, timeout=15)
        if result.returncode == 0 and os.path.exists(test_file) and os.path.getsize(test_file) > 0:
            print(f"✓ Video stream '{video_url}' is accessible")
            try:
                os.remove(test_file)
            except:
                pass
            return True
        else:
            print(f"✗ Video stream '{video_url}' test failed: {result.stderr[:200]}...")
            return False
    except subprocess.TimeoutExpired:
        print(f"✗ Video stream '{video_url}' test timed out")
        return False
    except Exception as e:
        print(f"✗ Video stream '{video_url}' test error: {e}")
        return False

# ------------------- Validate Output File -------------------
def validate_output_file(file_path):
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', file_path],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            import json
            data = json.loads(result.stdout)
            streams = data.get('streams', [])
            video_streams = [s for s in streams if s['codec_type'] == 'video']
            audio_streams = [s for s in streams if s['codec_type'] == 'audio']
            if video_streams and audio_streams:
                print(f"✓ Output file '{file_path}' is valid with {len(video_streams)} video stream(s) and {len(audio_streams)} audio stream(s)")
                return True
            else:
                print(f"✗ Output file '{file_path}' is invalid: Missing {'video' if not video_streams else 'audio'} stream")
                return False
        else:
            print(f"✗ Output file '{file_path}' is invalid: ffprobe error: {result.stderr[:200]}...")
            return False
    except Exception as e:
        print(f"✗ Error validating output file '{file_path}': {e}")
        return False

# ------------------- Camera Selection -------------------
def select_camera():
    print("\n=== Camera Selection ===")
    print("1. Default camera (built-in/USB camera)")
    print("2. External IP webcam")
    print("3. Integrated devices")
    while True:
        choice = input("Select camera (1, 2, or 3): ").strip()
        if choice == '1':
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
            print(f"\nIP Camera URL: {ip_url}")
            if not test_video_stream(ip_url):
                print(f"Error: Video stream at {ip_url} is not accessible. Please check the IP Webcam app and network.")
                continue
            audio_url = ip_url.replace('/video', '/audio.opus')
            if not test_audio_stream(audio_url):
                print(f"Warning: Audio stream at {audio_url} is not accessible.")
                audio_url_aac = ip_url.replace('/video', '/audio.aac')
                print(f"Trying fallback audio stream: {audio_url_aac}")
                if test_audio_stream(audio_url_aac):
                    print(f"Fallback audio stream {audio_url_aac} is accessible.")
                    audio_url = audio_url_aac
                else:
                    print("Warning: Fallback audio stream also inaccessible. Recording may not include audio.")
            print("Options:")
            print("1. Record video")
            print("2. Live stream view")
            while True:
                ip_choice = input("Select option (1 or 2): ").strip()
                if ip_choice == '1':
                    return (ip_url, audio_url), 0
                elif ip_choice == '2':
                    return ('live', ip_url, audio_url), 0
                else:
                    print("Invalid choice. Please enter 1 or 2.")
        elif choice == '3':
            if not INTEGRATED_DEVICES:
                print("No integrated devices configured.")
                continue
            print("\nAvailable integrated devices:")
            for i, device in enumerate(INTEGRATED_DEVICES, 1):
                print(f"  {i}. {device['name']} ({device['ip']})")
            while True:
                try:
                    dev_choice = input(f"Select device (1-{len(INTEGRATED_DEVICES)}) or press Enter to return: ").strip()
                    if not dev_choice:
                        break
                    dev_index = int(dev_choice) - 1
                    if 0 <= dev_index < len(INTEGRATED_DEVICES):
                        selected_device = INTEGRATED_DEVICES[dev_index]
                        ip_url = selected_device['ip']
                        print(f"\nSelected device: {selected_device['name']}")
                        print(f"IP Camera URL: {ip_url}")
                        if not test_video_stream(ip_url):
                            print(f"Error: Video stream at {ip_url} is not accessible. Please check the device and network.")
                            continue
                        audio_url = ip_url.replace('/video', '/audio.opus')
                        if not test_audio_stream(audio_url):
                            print(f"Warning: Audio stream at {audio_url} is not accessible.")
                            audio_url_aac = ip_url.replace('/video', '/audio.aac')
                            print(f"Trying fallback audio stream: {audio_url_aac}")
                            if test_audio_stream(audio_url_aac):
                                print(f"Fallback audio stream {audio_url_aac} is accessible.")
                                audio_url = audio_url_aac
                            else:
                                print("Warning: Fallback audio stream also inaccessible. Recording may not include audio.")
                        print("Options:")
                        print("1. Record video")
                        print("2. Live stream view")
                        while True:
                            ip_choice = input("Select option (1 or 2): ").strip()
                            if ip_choice == '1':
                                return (ip_url, audio_url), 0
                            elif ip_choice == '2':
                                return ('live', ip_url, audio_url), 0
                            else:
                                print("Invalid choice. Please enter 1 or 2.")
                    else:
                        print(f"Invalid choice. Please enter 1-{len(INTEGRATED_DEVICES)}")
                except ValueError:
                    print("Invalid input. Please enter a number.")
        else:
            print("Invalid choice. Please enter 1, 2, or 3.")

# ------------------- Close Browser Tabs -------------------
def close_browser_tabs(url):
    try:
        if sys.platform.startswith('win'):
            import subprocess
            subprocess.run(['taskkill', '/f', '/im', 'chrome.exe'], capture_output=True)
            subprocess.run(['taskkill', '/f', '/im', 'firefox.exe'], capture_output=True)
            subprocess.run(['taskkill', '/f', '/im', 'msedge.exe'], capture_output=True)
            print("Browser tabs closed")
    except:
        print("Could not close browser tabs automatically - please close manually")

# ------------------- Live Stream Function -------------------
def start_live_stream(camera_url, audio_url):
    print(f"\n=== Starting Live Stream ===")
    print(f"Camera URL: {camera_url}")
    live_server = LiveStreamServer(camera_url)
    live_url = live_server.start_server()
    if live_url:
        print(f"Live stream available at: {live_url}")
        print("Opening in default web browser...")
        try:
            webbrowser.open(live_url)
            print("✓ Browser opened successfully")
        except Exception as e:
            print(f"Could not open browser automatically: {e}")
            print(f"Please manually open this URL in your browser: {live_url}")
        print("\n" + "="*50)
        print("🎥 LIVE STREAM ACTIVE (VIDEO ONLY)")
        print("="*50)
        print(f"Stream URL: {live_url}")
        print(f"Camera: {camera_url}")
        print("="*50)
        print('Type "stop" and press Enter to stop the live stream')
        print("="*50)
        stop_event = threading.Event()
        def check_input():
            while not stop_event.is_set():
                if sys.platform.startswith('win'):
                    import msvcrt
                    if msvcrt.kbhit():
                        user_input = input().strip().lower()
                        if user_input == 'stop':
                            stop_event.set()
                            break
                    time.sleep(0.05)
                else:
                    if select.select([sys.stdin], [], [], 0.05)[0]:
                        user_input = input().strip().lower()
                        if user_input == 'stop':
                            stop_event.set()
                            break
        input_thread = threading.Thread(target=check_input, daemon=True)
        input_thread.start()
        try:
            while not stop_event.is_set():
                time.sleep(0.1)
            cleanup_thread = threading.Thread(target=live_server.stop_server, daemon=True)
            cleanup_thread.start()
            print("Live stream stopping in background...")
        except KeyboardInterrupt:
            stop_event.set()
            cleanup_thread = threading.Thread(target=live_server.stop_server, daemon=True)
            cleanup_thread.start()
            print("Live stream stopping in background...")
        finally:
            stop_event.set()
            input_thread.join(timeout=2)
            cleanup_thread.join(timeout=2)

# ------------------- Build FFmpeg Command -------------------
def build_ffmpeg_command(camera_info, output_path):
    camera_name, method = camera_info
    if isinstance(camera_name, tuple) and camera_name[0].startswith('http'):
        video_url, audio_url = camera_name
        ffmpeg_command = [
            'ffmpeg',
            '-y',
            '-loglevel', 'info',
            '-re',
            '-fflags', '+nobuffer',
            '-reconnect', '1',
            '-reconnect_streamed', '1',
            '-reconnect_on_network_error', '1',
            '-reconnect_delay_max', '5',
            '-timeout', '5000000',
            '-f', 'mpjpeg',
            '-itsoffset', '5',
            '-i', video_url,
            '-i', audio_url,
            '-c:v', 'libx264',
            '-preset', 'fast',
            '-crf', '23',
            '-pix_fmt', 'yuv420p',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-strict', '-2',
            '-map', '0:v:0',
            '-map', '1:a:0',
            '-async', '1',
            '-shortest',
            '-f', 'mp4',
            output_path
        ]
        return ffmpeg_command, None
    else:
        if method == 1:
            input_param = f'video={camera_name}'
        elif method == 2:
            input_param = f'video="{camera_name}"'
        else:
            input_param = f'video={camera_name}'
        return [
            'ffmpeg',
            '-y',
            '-loglevel', 'info',
            '-f', 'dshow',
            '-i', f'{input_param}:audio="Microphone (your-microphone-name)"',
            '-c:v', 'libx264',
            '-preset', 'fast',
            '-crf', '23',
            '-pix_fmt', 'yuv420p',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-r', '30',
            '-s', '1280x720',
            '-f', 'mp4',
            output_path
        ], None

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
        upload_scheduler.start_scheduler()
        usb_drive = find_removable_drive()
        if not usb_drive:
            print("No removable drive found or drive is not writable. Insert a USB drive with write permissions and try again.")
            sys.exit()
        video_folder = os.path.join(usb_drive, 'captured_videos')
        os.makedirs(video_folder, exist_ok=True)

        # Check for existing files in video_folder and queue them for upload if not in S3
        print("Checking for existing video files not uploaded to S3...")
        for file_name in os.listdir(video_folder):
            if file_name.endswith('.mp4'):
                file_path = os.path.join(video_folder, file_name)
                if os.path.isfile(file_path) and not upload_scheduler.check_file_exists_in_s3(file_name):
                    logger.info(f"Found local file not in S3: {file_name}. Queuing for upload.")
                    upload_scheduler.queue_upload(file_path)

        print("Note: S3 uploads may fail due to invalid credentials. Update AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and S3_BUCKET_NAME in the script.")
        selected_camera = select_camera()
        if selected_camera[0] is None:
            print("No camera selected. Exiting.")
            sys.exit()
        camera_info, method = selected_camera
        if isinstance(camera_info, tuple) and camera_info[0] == 'live':
            start_live_stream(camera_info[1], camera_info[2])
            print("\nReturning to main menu...")
            selected_camera = select_camera()
            if selected_camera[0] is None:
                print("No camera selected. Exiting.")
                sys.exit()
            camera_info, method = selected_camera
        if isinstance(camera_info, str) and not camera_info.startswith('http'):
            print(f"Selected camera: {camera_info} (method {method})")
        else:
            print(f"Selected camera: {'IP Webcam' if isinstance(camera_info, tuple) else camera_info}")
            if isinstance(camera_info, tuple):
                print(f"Video URL: {camera_info[0]}")
                print(f"Audio URL: {camera_info[1]}")
        while True:
            action = input('\nType "start" to begin recording, "camera" to change camera, "live" for live stream, or "exit" to quit: ').strip().lower()
            if action == 'start':
                if isinstance(camera_info, tuple) and camera_info[0] == 'live':
                    print("Current camera is set to live stream mode. Please change camera to record.")
                    continue
                start_time = datetime.now()
                temp_filename = f"temp_recording_{start_time.strftime('%Y%m%d_%H%M%S')}.mp4"
                temp_output_path = os.path.join(video_folder, temp_filename)
                print(f"Starting recording at: {start_time.strftime('%Y-%m-%d %I:%M:%S %p')}")
                print(f"Temporary file: {temp_output_path}")
                ffmpeg_command, _ = build_ffmpeg_command(selected_camera, temp_output_path)
                print(f"FFmpeg command: {' '.join(ffmpeg_command)}")
                try:
                    process = subprocess.Popen(ffmpeg_command, stdin=subprocess.PIPE, 
                                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    def log_ffmpeg_errors():
                        stderr_output = []
                        for line in process.stderr:
                            if line.strip():
                                stderr_output.append(line.strip())
                                logger.error(line.strip())
                        return stderr_output
                    error_thread = threading.Thread(target=log_ffmpeg_errors, daemon=True)
                    error_thread.start()
                except Exception as e:
                    print(f"Error starting FFmpeg: {e}")
                    continue
                print('Recording started. Type "stop" and press Enter to stop recording.')
                stop_event = threading.Event()
                input_thread = threading.Thread(target=monitor_input, args=(stop_event,))
                input_thread.daemon = True
                input_thread.start()
                recording_start_time = time.time()
                process_finished = False
                while not stop_event.is_set():
                    if process.poll() is not None:
                        process_finished = True
                        break
                    if time.time() - recording_start_time > 3 and process.poll() is not None:
                        print("FFmpeg process ended unexpectedly. Check video_recorder.log for errors.")
                        process_finished = True
                        break
                    time.sleep(0.1)
                end_time = datetime.now()
                if not process_finished:
                    print("Stopping recording...")
                    try:
                        if process.stdin and not process.stdin.closed:
                            process.stdin.write('q\n')
                            process.stdin.flush()
                        try:
                            process.wait(timeout=5)
                            print(f'Recording stopped gracefully at: {end_time.strftime("%Y-%m-%d %I:%M:%S %p")}')
                        except subprocess.TimeoutExpired:
                            print('FFmpeg taking too long to stop, force terminating...')
                            process.terminate()
                            try:
                                process.wait(timeout=3)
                            except subprocess.TimeoutExpired:
                                process.kill()
                                process.wait()
                            print('Recording force stopped.')
                    except Exception as e:
                        logger.error(f"Error stopping FFmpeg: {e}")
                        try:
                            process.terminate()
                            process.wait(timeout=3)
                        except:
                            process.kill()
                            process.wait()
                else:
                    if process.returncode != 0:
                        print(f"Recording failed with exit code {process.returncode}. Check video_recorder.log for FFmpeg errors.")
                stop_event.set()
                if input_thread.is_alive():
                    input_thread.join(timeout=2)
                if os.path.exists(temp_output_path) and os.path.getsize(temp_output_path) > 0:
                    if validate_output_file(temp_output_path):
                        final_filename = generate_filename(start_time, end_time)
                        final_output_path = os.path.join(video_folder, final_filename)
                        try:
                            os.rename(temp_output_path, final_output_path)
                            print(f'Recording saved as: {final_filename}')
                            print(f"Please check the file at {final_output_path} with VLC or another media player.")
                            upload_scheduler.queue_upload(final_output_path)
                        except Exception as e:
                            logger.error(f"Error renaming file: {e}")
                            print(f'Recording saved as: {temp_filename}')
                            print(f"Please check the file at {temp_output_path} with VLC or another media player.")
                            upload_scheduler.queue_upload(temp_output_path)
                    else:
                        print(f'Output file {temp_output_path} is invalid. Check video_recorder.log for errors.')
                else:
                    print(f'Recording file not found or empty at {temp_output_path}. Check video_recorder.log for errors.')
                stop_event.clear()
            elif action == 'camera':
                selected_camera = select_camera()
                if selected_camera[0] is None:
                    print("No camera selected. Keeping current camera.")
                    continue
                camera_info, method = selected_camera
                if isinstance(camera_info, tuple) and camera_info[0] == 'live':
                    start_live_stream(camera_info[1], camera_info[2])
                    print("\nReturning to camera selection...")
                    selected_camera = select_camera()
                    if selected_camera[0] is None:
                        print("No camera selected. Keeping previous camera.")
                        continue
                    camera_info, method = selected_camera
                if isinstance(camera_info, str) and not camera_info.startswith('http'):
                    print(f"Camera changed to: {camera_info} (method {method})")
                else:
                    print(f"Camera changed to: {'IP Webcam' if isinstance(camera_info, tuple) else camera_info}")
                    if isinstance(camera_info, tuple):
                        print(f"Video URL: {camera_info[0]}")
                        print(f"Audio URL: {camera_info[1]}")
            elif action == 'live':
                if isinstance(camera_info, tuple) and camera_info[0] == 'live':
                    start_live_stream(camera_info[1], camera_info[2])
                elif isinstance(camera_info, tuple):
                    start_live_stream(camera_info[0], camera_info[1])
                else:
                    print("Live stream is only available for IP cameras.")
                    print("Please change camera to an IP webcam to use live stream feature.")
            elif action == 'exit':
                print("Stopping upload scheduler...")
                upload_scheduler.stop_scheduler()
                print("Exiting...")
                sys.exit()
            else:
                print('Invalid command. Type "start" to record, "camera" to change camera, "live" for live stream, or "exit" to quit.')
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
