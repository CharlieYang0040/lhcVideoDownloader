import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile


FFMPEG_SHARED_ZIP_URL = (
    "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/"
    "ffmpeg-master-latest-win64-gpl-shared.zip"
)


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


def setup_binaries(skip_ytdlp_update=False, force_ffmpeg=False):
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

    # Only download ffmpeg if forced, missing, or not executable/working
    if not force_ffmpeg and is_executable_working(ffmpeg_path) and is_executable_working(ffprobe_path):
        print("ffmpeg.exe and ffprobe.exe are already present and working.")
    else:
        print("Downloading FFmpeg shared build...")
        zip_path = os.path.join(libs_dir, 'ffmpeg.zip')

        try:
            download_file(FFMPEG_SHARED_ZIP_URL, zip_path)
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

                if not bin_dir:
                    raise RuntimeError("Failed to find extracted ffmpeg bin directory.")

                # Remove stale DLLs and unused ffplay.exe before installing new shared binaries
                for existing_name in os.listdir(ffmpeg_dir):
                    if existing_name.lower().endswith(".dll") or existing_name.lower() == "ffplay.exe":
                        try:
                            os.remove(os.path.join(ffmpeg_dir, existing_name))
                        except OSError:
                            pass

                for entry in os.listdir(bin_dir):
                    lower = entry.lower()
                    if entry in ('ffmpeg.exe', 'ffprobe.exe') or lower.endswith('.dll'):
                        src = os.path.join(bin_dir, entry)
                        if os.path.isfile(src):
                            dst = os.path.join(ffmpeg_dir, entry)
                            tmp_dst = dst + ".tmp"
                            shutil.copy2(src, tmp_dst)
                            os.replace(tmp_dst, dst)
                print("ffmpeg shared setup completed.")
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
    parser.add_argument(
        "--force-ffmpeg",
        action="store_true",
        help="Force re-download and replace FFmpeg binaries with the shared build.",
    )
    args = parser.parse_args()

    print("Checking external binaries setup (yt-dlp, ffmpeg, deno)...")
    try:
        setup_binaries(
            skip_ytdlp_update=args.no_ytdlp_update,
            force_ffmpeg=args.force_ffmpeg,
        )
        print("Binary setup verified.")
    except Exception as e:
        print(f"Error checking binaries: {e}")
        sys.exit(1)
