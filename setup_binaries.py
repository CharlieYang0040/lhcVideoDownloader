import os
import urllib.request
import zipfile
import shutil
import sys
import subprocess
import time

def download_file(url, dest_path):
    print(f"Downloading {os.path.basename(dest_path)}...")
    urllib.request.urlretrieve(url, dest_path)
    print(f"Downloaded successfully to {dest_path}")

def setup_binaries():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    libs_dir = os.path.join(base_dir, 'libs')
    
    # Define exact expected directories inside `libs`
    ytdlp_dir = os.path.join(libs_dir, 'yt-dlp')
    ffmpeg_dir = os.path.join(libs_dir, 'ffmpeg')
    
    os.makedirs(ytdlp_dir, exist_ok=True)
    os.makedirs(ffmpeg_dir, exist_ok=True)

    ytdlp_path = os.path.join(ytdlp_dir, 'yt-dlp.exe')
    ffmpeg_path = os.path.join(ffmpeg_dir, 'ffmpeg.exe')

    # Download yt-dlp if it doesn't exist
    if not os.path.exists(ytdlp_path):
        yt_dlp_url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
        download_file(yt_dlp_url, ytdlp_path)
    else:
        print("yt-dlp.exe is already present.")

    print("Checking for yt-dlp updates...")
    try:
        subprocess.run([ytdlp_path, "-U"])
    except Exception as e:
        print(f"Failed to update yt-dlp: {e}")

    # Download ffmpeg if it doesn't exist or needs update
    ffmpeg_needs_update = False
    if os.path.exists(ffmpeg_path):
        try:
            # Get latest version from gyan.dev
            req = urllib.request.Request("https://www.gyan.dev/ffmpeg/builds/release-version", headers={'User-Agent': 'Mozilla/5.0'})
            remote_version = urllib.request.urlopen(req, timeout=5).read().decode('utf-8').strip()
            
            # Get local version
            out = subprocess.check_output([ffmpeg_path, "-version"], text=True)
            # Example output: ffmpeg version 8.1-essentials_build-www.gyan.dev Copyright...
            local_version_full = out.split()[2]
            local_version = local_version_full.split('-')[0]
            
            if local_version != remote_version:
                print(f"ffmpeg update available: {local_version} -> {remote_version}")
                ffmpeg_needs_update = True
            else:
                print(f"ffmpeg.exe is up to date (version: {local_version}).")
        except Exception as e:
            print(f"Failed to check ffmpeg version: {e}")
            # Fallback to checking age if version check fails
            file_age_days = (time.time() - os.path.getmtime(ffmpeg_path)) / (60 * 60 * 24)
            if file_age_days > 30:
                print(f"ffmpeg is {file_age_days:.1f} days old. Marking for update as fallback.")
                ffmpeg_needs_update = True
            else:
                print(f"ffmpeg.exe is up to date (fallback age check: {file_age_days:.1f} days).")

    if not os.path.exists(ffmpeg_path) or ffmpeg_needs_update:
        print("Downloading ffmpeg...")
        # Get gyan.dev latest ffmpeg essentials build
        ffmpeg_zip_url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
        zip_path = os.path.join(libs_dir, 'ffmpeg.zip')
        
        download_file(ffmpeg_zip_url, zip_path)
        
        print("Extracting ffmpeg...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(libs_dir)
            
        os.remove(zip_path)
        
        # Determine the extracted folder name (it contains version, so it varies)
        extracted_dirs = [d for d in os.listdir(libs_dir) if os.path.isdir(os.path.join(libs_dir, d)) and 'ffmpeg' in d and d != 'ffmpeg']
        if extracted_dirs:
            extracted_folder = os.path.join(libs_dir, extracted_dirs[0])
            bin_dir = os.path.join(extracted_folder, 'bin')
            
            # Move binaries to expected location
            for exe in ['ffmpeg.exe', 'ffprobe.exe', 'ffplay.exe']:
                src = os.path.join(bin_dir, exe)
                if os.path.exists(src):
                    shutil.move(src, os.path.join(ffmpeg_dir, exe))
                    
            # Cleanup the extracted directory
            shutil.rmtree(extracted_folder)
            print("ffmpeg setup completed.")
        else:
            print("Failed to find extracted ffmpeg folder.")
    else:
         print("ffmpeg.exe is already present.")

if __name__ == "__main__":
    print("Checking external binaries setup...")
    try:
        setup_binaries()
        print("Binary setup verified.")
    except Exception as e:
        print(f"Error checking binaries: {e}")
        sys.exit(1)
