import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile


def download_file(url, dest_path):
    print(f"Downloading {os.path.basename(dest_path)}...")
    urllib.request.urlretrieve(url, dest_path)
    print(f"Downloaded successfully to {dest_path}")


def is_executable_working(exe_path, args=("-version",), timeout=10):
    if not os.path.isfile(exe_path):
        return False
    try:
        result = subprocess.run(
            [exe_path, *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def setup_binaries(skip_ytdlp_update=False):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    libs_dir = os.path.join(base_dir, 'libs')

    # Define exact expected directories inside `libs`
    ytdlp_dir = os.path.join(libs_dir, 'yt-dlp')
    ffmpeg_dir = os.path.join(libs_dir, 'ffmpeg')
    deno_dir = os.path.join(libs_dir, 'deno')

    os.makedirs(ytdlp_dir, exist_ok=True)
    os.makedirs(ffmpeg_dir, exist_ok=True)
    os.makedirs(deno_dir, exist_ok=True)

    ytdlp_path = os.path.join(ytdlp_dir, 'yt-dlp.exe')
    ffmpeg_path = os.path.join(ffmpeg_dir, 'ffmpeg.exe')
    ffprobe_path = os.path.join(ffmpeg_dir, 'ffprobe.exe')
    deno_path = os.path.join(deno_dir, 'deno.exe')

    # Download yt-dlp if it doesn't exist
    if not os.path.exists(ytdlp_path):
        yt_dlp_url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
        download_file(yt_dlp_url, ytdlp_path)
    else:
        print("yt-dlp.exe is already present.")

    if not skip_ytdlp_update:
        print("Checking for yt-dlp updates...")
        try:
            subprocess.run([ytdlp_path, "-U"])
        except Exception as e:
            print(f"Failed to update yt-dlp: {e}")

    # Download Deno if it doesn't exist
    if not os.path.exists(deno_path):
        print("Downloading Deno JavaScript runtime...")
        deno_zip_url = "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip"
        deno_zip_path = os.path.join(libs_dir, 'deno.zip')
        try:
            download_file(deno_zip_url, deno_zip_path)
            print("Extracting Deno...")
            with zipfile.ZipFile(deno_zip_path, 'r') as zip_ref:
                zip_ref.extractall(deno_dir)
            print("Deno setup completed.")
        finally:
            if os.path.exists(deno_zip_path):
                os.remove(deno_zip_path)
    else:
        print("deno.exe is already present.")

    # Only download ffmpeg if missing or not executable/working
    if is_executable_working(ffmpeg_path) and is_executable_working(ffprobe_path):
        print("ffmpeg.exe and ffprobe.exe are already present and working.")
    else:
        print("ffmpeg is missing or not working. Downloading ffmpeg...")
        ffmpeg_zip_url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
        zip_path = os.path.join(libs_dir, 'ffmpeg.zip')

        try:
            download_file(ffmpeg_zip_url, zip_path)
            print("Extracting ffmpeg...")
            with tempfile.TemporaryDirectory(dir=libs_dir) as temp_extract_dir:
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(temp_extract_dir)

                bin_dir = None
                for root, dirs, _ in os.walk(temp_extract_dir):
                    if 'bin' in dirs:
                        candidate = os.path.join(root, 'bin')
                        if os.path.isfile(os.path.join(candidate, 'ffmpeg.exe')):
                            bin_dir = candidate
                            break

                if bin_dir:
                    for exe in ['ffmpeg.exe', 'ffprobe.exe', 'ffplay.exe']:
                        src = os.path.join(bin_dir, exe)
                        if os.path.isfile(src):
                            dst = os.path.join(ffmpeg_dir, exe)
                            tmp_dst = dst + ".tmp"
                            shutil.copy2(src, tmp_dst)
                            os.replace(tmp_dst, dst)
                    print("ffmpeg setup completed.")
                else:
                    raise RuntimeError("Failed to find extracted ffmpeg bin directory.")
        finally:
            if os.path.exists(zip_path):
                os.remove(zip_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Setup external binaries")
    parser.add_argument(
        "--no-ytdlp-update",
        action="store_true",
        help="Skip running yt-dlp -U during setup (handled at GUI startup).",
    )
    args = parser.parse_args()

    print("Checking external binaries setup (yt-dlp, ffmpeg, deno)...")
    try:
        setup_binaries(skip_ytdlp_update=args.no_ytdlp_update)
        print("Binary setup verified.")
    except Exception as e:
        print(f"Error checking binaries: {e}")
        sys.exit(1)
