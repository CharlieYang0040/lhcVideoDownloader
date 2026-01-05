import subprocess
import os
import re
from PySide6.QtCore import QObject, Signal, QThread
from src.utils.helpers import get_lib_path, check_js_runtime

class VideoDownloader(QObject):
    """
    Wrapper for yt-dlp execution.
    Emits signals for progress and logs.
    """
    progress_update = Signal(float, str, str) # progress %, speed, eta
    log_message = Signal(str)
    finished = Signal()
    error_occurred = Signal(str)

    def __init__(self, url, download_path, audio_only=False, cookies_browser=None, post_process=None):
        super().__init__()
        self.url = url
        self.download_path = download_path
        self.audio_only = audio_only
        self.cookies_browser = cookies_browser
        self.post_process = post_process # 'H264 (CPU)', 'NVENC H264', or None
        self.is_running = False
        self.process = None

    def start_download(self):
        self.is_running = True
        
        # Check for JS Runtime (Required for YouTube EJS)
        if "youtube.com" in self.url or "youtu.be" in self.url:
            js_runtime = check_js_runtime()
            if not js_runtime:
                self.error_occurred.emit(
                    "YouTube 다운로드를 위해 JavasScript 런타임(Deno)이 필요합니다.\n"
                    "https://deno.com 에서 설치해주세요."
                )
                return
        else:
             # Not youtube, might not need it, but good to have
             js_runtime = check_js_runtime()
        
        yt_dlp_path = get_lib_path('yt-dlp')
        ffmpeg_path = get_lib_path('ffmpeg')
        ffmpeg_dir = os.path.dirname(ffmpeg_path)

        if not yt_dlp_path or not os.path.exists(yt_dlp_path):
            self.error_occurred.emit("yt-dlp.exe not found in libs/yt-dlp/")
            return

        # Prepare command
        cmd = [
            yt_dlp_path,
            self.url,
            '--ffmpeg-location', ffmpeg_dir,
            '-o', os.path.join(self.download_path, '%(title)s.%(ext)s'),
            '--newline', # Important for real-time output parsing
            '--no-colors',
            '--progress-template', '%(progress._percent_str)s|%(progress.speed_str)s|%(progress.eta_str)s'
        ]

        # Explicitly pass JS Runtime if it's a path (bundled)
        if js_runtime and os.path.isabs(js_runtime):
             # Format: --js-runtimes "deno:/path/to/deno.exe"
             cmd.extend(['--js-runtimes', f'deno:{js_runtime}'])

        # Authentication (Cookies)
        # cookies_browser param now can be "browser:chrome" or "file:/path/to/cookies.txt"
        if self.cookies_browser:
            if self.cookies_browser.startswith("browser:"):
                browser_name = self.cookies_browser.split(":", 1)[1]
                cmd.extend(['--cookies-from-browser', browser_name])
            elif self.cookies_browser.startswith("file:"):
                file_path = self.cookies_browser.split(":", 1)[1]
                cmd.extend(['--cookies', file_path])
            # Fallback for legacy calls (if any)
            elif self.cookies_browser.lower() != "none" and ":" not in self.cookies_browser:
                 cmd.extend(['--cookies-from-browser', self.cookies_browser])

        # Audio / Video Selection
        if self.audio_only:
            cmd.extend(['-x', '--audio-format', 'mp3'])
        else:
            # Merge video+audio into mp4 for compatibility
            cmd.extend(['--merge-output-format', 'mp4'])

        # Post-Processing: REMOVED from yt-dlp args, will handle manually
        
        self.log_message.emit(f"Starting download: {' '.join(cmd)}")

        output_file = None
        duration_sec = 0.0

        try:
            # STARTUPINFO to hide console window on Windows
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            # Windows Korean encoding fix: usually cp949
            encoding = 'cp949' if os.name == 'nt' else 'utf-8'

            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding=encoding,
                errors='replace',
                startupinfo=startupinfo,
                bufsize=1,
                universal_newlines=True
            )

            # Read output
            while True and self.is_running:
                try:
                    line = self.process.stdout.readline()
                except Exception as e:
                    self.log_message.emit(f"Log read error: {e}")
                    continue

                if not line:
                    if self.process.poll() is not None:
                        break
                    continue

                line = line.strip()
                if not line:
                    continue

                # Cookie Error Detection
                if "Could not copy Chrome cookie database" in line:
                    self.error_occurred.emit(f"Cookie Error: Please close browser or check permissions.")
                    self.stop()
                    return

                # Capture Output Filename (Heuristic)
                if "[Merger] Merging formats into" in line:
                    match = re.search(r'Merging formats into "(.+?)"', line)
                    if match:
                        output_file = match.group(1)
                elif "[download] Destination:" in line and not output_file:
                    match = re.search(r'Destination: (.+)', line)
                    if match:
                        potential_file = match.group(1)
                        if not re.search(r'\.f\d+', potential_file): # Skip temp format files
                            output_file = potential_file

                # Parse progress
                if '|' in line and '%' in line:
                    parts = line.split('|')
                    if len(parts) >= 3:
                        percent_str = parts[0].strip().replace('%','')
                        speed = parts[1].strip()
                        eta = parts[2].strip()
                        try:
                            percent = float(percent_str)
                            self.progress_update.emit(percent, speed, eta)
                        except ValueError:
                            pass
                else:
                    self.log_message.emit(line)

            rc = self.process.poll()
            
            if not self.is_running:
                return # Cancelled

            if rc != 0:
                self.error_occurred.emit(f"Download failed with exit code {rc}")
                return

            # --- Post Processing (Manual Encoding) ---
            if self.post_process and self.post_process != "None" and output_file and os.path.exists(output_file):
                self.log_message.emit(f"Starting Post-Process: {self.post_process}")
                self.progress_update.emit(0, "Encoding...", "Calculating...") # Start at 0
                
                # Get Duration via ffprobe/ffmpeg first
                try:
                     probe_cmd = [ffmpeg_path, '-i', output_file]
                     probe_process = subprocess.run(
                        probe_cmd, 
                        stdout=subprocess.PIPE, 
                        stderr=subprocess.PIPE, 
                        text=True, 
                        encoding=encoding,
                        errors='replace',
                        startupinfo=startupinfo
                    )
                     # Find Duration: 00:03:59.12
                     match = re.search(r'Duration: (\d{2}):(\d{2}):(\d{2}\.\d{2})', probe_process.stderr)
                     if match:
                        h, m, s = match.groups()
                        duration_sec = float(h)*3600 + float(m)*60 + float(s)
                except Exception as e:
                    self.log_message.emit(f"Duration check failed: {e}")

                # Rename original to _input
                base, ext = os.path.splitext(output_file)
                input_file = f"{base}_raw{ext}"
                try:
                    if os.path.exists(input_file):
                        os.remove(input_file)
                    os.rename(output_file, input_file)
                except OSError as e:
                    self.error_occurred.emit(f"File rename failed: {e}")
                    return

                # Construct ffmpeg command
                ffmpeg_cmd = [ffmpeg_path, '-y', '-i', input_file]
                
                if self.post_process == 'NVENC H264':
                    ffmpeg_cmd.extend(['-c:v', 'h264_nvenc', '-rc:v', 'vbr_hq', '-cq:v', '19', '-b:v', '0'])
                elif self.post_process == 'H264 (CPU)':
                    ffmpeg_cmd.extend(['-c:v', 'libx264', '-crf', '23'])
                
                # Keep audio copy
                ffmpeg_cmd.extend(['-c:a', 'copy', output_file])

                self.log_message.emit(f"Encoding command: {' '.join(ffmpeg_cmd)}")

                # Run ffmpeg
                try:
                    enc_process = subprocess.Popen(
                        ffmpeg_cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding=encoding,
                        errors='replace',
                        startupinfo=startupinfo
                    )
                    
                    # Read logging from ffmpeg
                    while self.is_running:
                        line = enc_process.stdout.readline()
                        if not line:
                            if enc_process.poll() is not None:
                                break
                            continue
                        
                        line = line.strip()
                        self.log_message.emit(f"[FFmpeg] {line}")
                        
                        # Parse Progress
                        # time=00:00:05.12
                        if duration_sec > 0 and "time=" in line:
                            match = re.search(r'time=(\d{2}):(\d{2}):(\d{2}\.\d{2})', line)
                            if match:
                                h, m, s = match.groups()
                                current_sec = float(h)*3600 + float(m)*60 + float(s)
                                percent = (current_sec / duration_sec) * 100
                                self.progress_update.emit(percent, "Encoding", "")

                    
                    if enc_process.returncode == 0:
                        self.log_message.emit("Encoding completed.")
                        self.progress_update.emit(100, "Done", "")
                        # Remove raw file
                        try:
                            os.remove(input_file)
                        except:
                            pass
                        self.finished.emit()
                    else:
                        self.error_occurred.emit(f"Encoding failed: {enc_process.returncode}")
                        # Restore file
                        if os.path.exists(input_file) and not os.path.exists(output_file):
                            os.rename(input_file, output_file)

                except Exception as e:
                    self.error_occurred.emit(f"Encoding process error: {e}")

            else:
                self.finished.emit()

        except Exception as e:
            self.error_occurred.emit(f"An error occurred: {str(e)}")
        finally:
            self.is_running = False

    def stop(self):
        self.is_running = False
        if self.process:
            try:
                self.process.terminate()
            except:
                pass

class DownloaderThread(QThread):
    def __init__(self, downloader):
        super().__init__()
        self.downloader = downloader

    def run(self):
        self.downloader.start_download()
