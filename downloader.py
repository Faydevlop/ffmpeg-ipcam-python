import boto3
import ffmpeg
import os
import subprocess
import json
import psutil
from datetime import datetime
import re

# ------------------- AWS S3 Setup -------------------
AWS_ACCESS_KEY_ID = ''
AWS_SECRET_ACCESS_KEY = ''
AWS_REGION = 'eu-north-1'
BUCKET_NAME = 'my-bucket'
PREFIX = 'recorded-videos/'

# Initialize S3 client
try:
    s3_client = boto3.client(
        's3',
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=AWS_REGION
    )
except Exception as e:
    print(f"Failed to initialize S3 client: {e}")
    s3_client = None

# ------------------- Find Removable Drive -------------------
def find_removable_drive():
    partitions = psutil.disk_partitions(all=False)
    for partition in partitions:
        if 'removable' in partition.opts.lower():
            try:
                test_file = os.path.join(partition.mountpoint, 'test_write.txt')
                with open(test_file, 'w') as f:
                    f.write('test')
                os.remove(test_file)
                return os.path.join(partition.mountpoint, 'captured_videos')
            except (OSError, PermissionError) as e:
                print(f"Cannot access drive {partition.mountpoint}: {e}")
                continue
    return None

# ------------------- Parse Filename to Epoch (in seconds) -------------------
def parse_filename_to_epoch(filename):
    pattern = r'captured_video_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_[AP]M)_to_(\d{2}-\d{2}-\d{2}_[AP]M)\.mp4'
    match = re.match(pattern, os.path.basename(filename))
    if match:
        start_str, end_str = match.groups()
        try:
            start_dt = datetime.strptime(start_str, '%Y-%m-%d_%I-%M-%S_%p')
            end_dt = datetime.strptime(f"{start_str.split('_')[0]}_{end_str}", '%Y-%m-%d_%I-%M-%S_%p')
            return int(start_dt.timestamp()), int(end_dt.timestamp())
        except ValueError as e:
            print(f"Error parsing timestamp in filename {filename}: {e}")
            return None, None
    return None, None

# ------------------- List Videos -------------------
def list_videos(start_ms, end_ms):
    # Convert milliseconds to seconds for comparison
    start_epoch = start_ms // 1000
    end_epoch = end_ms // 1000
    video_files = []
    # Check S3
    if s3_client:
        try:
            response = s3_client.list_objects_v2(Bucket=BUCKET_NAME, Prefix=PREFIX)
            for item in response.get('Contents', []):
                key = item['Key']
                if key.endswith('.mp4'):
                    start_time, end_time = parse_filename_to_epoch(key)
                    if start_time and end_time:
                        # Include video if its time range overlaps with the input range
                        if (start_epoch <= end_time and end_epoch >= start_time):
                            video_files.append(('s3', key, start_time))
        except Exception as e:
            print(f"Error accessing S3: {e}")

    # Check local removable drive
    local_folder = find_removable_drive()
    if local_folder and os.path.exists(local_folder):
        try:
            for file in os.listdir(local_folder):
                if file.endswith('.mp4'):
                    full_path = os.path.join(local_folder, file)
                    start_time, end_time = parse_filename_to_epoch(full_path)
                    if start_time and end_time:
                        # Include video if its time range overlaps with the input range
                        if (start_epoch <= end_time and end_epoch >= start_time):
                            video_files.append(('local', full_path, start_time))
        except Exception as e:
            print(f"Error accessing local folder {local_folder}: {e}")

    return video_files

# ------------------- Download Video -------------------
def download_video(source, source_path, local_filename):
    os.makedirs("download_video", exist_ok=True)
    full_path = os.path.join("download_video", local_filename)
    if source == 's3':
        try:
            s3_client.download_file(BUCKET_NAME, source_path, full_path)
            return full_path
        except Exception as e:
            print(f"Error downloading from S3: {e}")
            return None
    else:  # local
        try:
            import shutil
            shutil.copy(source_path, full_path)
            return full_path
        except Exception as e:
            print(f"Error copying from local storage: {e}")
            return None

# ------------------- Get Video Duration -------------------
def get_video_duration(filename):
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration", "-of", "json", filename],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        output = json.loads(result.stdout)
        return float(output["format"]["duration"])
    except Exception as e:
        print(f"Error getting video duration for {filename}: {e}")
        return 0

# ------------------- Crop Video -------------------
def crop_video(input_path, output_path, start_time, end_time):
    try:
        ffmpeg.input(input_path, ss=start_time, t=end_time - start_time) \
              .output(output_path, c='copy') \
              .run(overwrite_output=True)
        return True
    except Exception as e:
        print(f"Error cropping video: {e}")
        return False

# ------------------- Main -------------------
def main():
    try:
        # Get millisecond timestamp input
        while True:
            try:
                start_ms = int(input("Enter start timestamp in milliseconds (e.g., 1752298630000): "))
                end_ms = int(input("Enter end timestamp in milliseconds (e.g., 1752298635000): "))
                if start_ms >= end_ms:
                    print("End timestamp must be greater than start timestamp.")
                    continue
                if start_ms < 0 or end_ms < 0:
                    print("Timestamps must be positive.")
                    continue
                break
            except ValueError:
                print("Please enter valid millisecond timestamps.")

        # Convert to seconds for internal processing and display
        start_epoch = start_ms // 1000
        end_epoch = end_ms // 1000

        # Convert to human-readable for user confirmation
        start_dt = datetime.fromtimestamp(start_epoch)
        end_dt = datetime.fromtimestamp(end_epoch)
        print(f"Searching for videos between {start_dt.strftime('%Y-%m-%d %I:%M:%S %p')} and {end_dt.strftime('%Y-%m-%d %I:%M:%S %p')}")

        # List videos within the time range
        videos = list_videos(start_ms, end_ms)
        if not videos:
            print("No file found in the specified time range.")
            return

        # Automatically select the first video
        selected_source, selected_path, video_start_epoch = videos[0]
        local_video_filename = os.path.basename(selected_path)

        print(f"\nDownloading {'from S3' if selected_source == 's3' else 'from local storage'}: {selected_path}...")
        local_video_path = download_video(selected_source, selected_path, local_video_filename)
        if not local_video_path:
            print("Failed to download/copy video.")
            return

        video_duration = get_video_duration(local_video_path)
        print(f"Downloaded to: {local_video_path}")
        print(f"Video duration: {video_duration:.2f} seconds")

        # Calculate crop times relative to video start
        start_crop = (start_ms // 1000) - video_start_epoch
        end_crop = (end_ms // 1000) - video_start_epoch

        # Validate crop times
        if start_crop < 0:
            start_crop = 0
        if end_crop > video_duration:
            end_crop = video_duration
        if start_crop >= end_crop:
            print("Invalid crop range: Start time is after or equal to end time.")
            return

        cropped_path = os.path.join("download_video", f"cropped_{local_video_filename}")
        print("Cropping video...")
        if crop_video(local_video_path, cropped_path, start_crop, end_crop):
            print(f"Cropped video saved as {cropped_path}")
            # Delete original downloaded video
            try:
                os.remove(local_video_path)
                print("Original downloaded video deleted.")
            except Exception as e:
                print(f"Error deleting original video: {e}")
        else:
            print("Cropping failed. Keeping original downloaded video.")
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
    except Exception as e:
        print(f"Unexpected error: {e}")

if __name__ == "__main__":
    main()
