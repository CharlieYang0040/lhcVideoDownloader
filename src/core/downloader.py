import os
import subprocess
import threading
import re
import sys
import logging
import locale
import shutil
import glob
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

    def __init__(self, url, path, audio_only, cookies, codec, preset, target_ext, overwrite=False, threads=1, fragments=5):
        super().__init__()
        self.url = url
        self.download_path = path
        self.audio_only = audio_only
        self.cookies = cookies
        self.codec = codec
        self.preset = preset
        self.target_ext = target_ext
        self.overwrite = overwrite
        self.threads = threads
        self.fragments = fragments
        
        self.is_running = False
        self.process = None
        self.current_filename = None
        self.logger = logging.getLogger(self.__class__.__name__)

    def start_download(self):
        self.is_running = True
        self.logger.debug(f"Starting download for URL: {self.url}")
        self.logger.debug(f"Options: Audio={self.audio_only}, Codec={self.codec}, Ext={self.target_ext}, Overwrite={self.overwrite}")
        
        # Determine paths
        yt_dlp_path = get_lib_path('yt-dlp')
        ffmpeg_path = get_lib_path('ffmpeg')
        
        # Check dependencies
        if not yt_dlp_path or not os.path.exists(yt_dlp_path):
            self.error_occurred.emit("yt-dlp.exe not found.")
            return

        # JS Runtime Check
        js_runtime = check_js_runtime()
        if not js_runtime:
             self.error_occurred.emit("Javascript runtime not found. Deno or Node.js is required.")
             return
            
        # Build Command
        cmd = [yt_dlp_path, '--newline'] # newline for easier parsing
        
        # Encoding for subprocess
        # Windows console often uses cp949/cp950 for Korean
        encoding = locale.getpreferredencoding()
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        
        # Args
        cmd.extend(['-o', f"{self.download_path}\\%(title)s.%(ext)s"])
        
        # Overwrite
        if not self.overwrite:
            cmd.append('--no-overwrites')
        else:
            cmd.append('--force-overwrites')

        # Fragments (Download Speed)
        if self.fragments > 1:
            cmd.extend(['-N', str(self.fragments)])

        # Smart Format Selection or Transcoding Logic
        is_smart_selection = False
        if self.codec == "변환 없음" or self.codec == "None":
            is_smart_selection = True
            if self.audio_only:
                 audio_fmt = self.target_ext if self.target_ext else 'mp3'
                 # Best audio available for the container
                 cmd.extend(['-f', f"bestaudio[ext={audio_fmt}]/bestaudio/best"])
                 cmd.extend(['-x', '--audio-format', audio_fmt]) 
            elif self.target_ext:
                 # Video: Try to get native container/codec to avoid transcoding interactions
                 target = self.target_ext.lower()
                 
                 if target == 'mp4':
                     # Prioritize Resolution first (>1080p), then Compatibility (AVC/H.264)
                     # 1. Try for 4K/8K (likely VP9/AV1)
                     # 2. If not found, try for H.264 (likely 1080p)
                     # 3. Fallback to best available
                     cmd.extend(['-f', 
                        "bestvideo[height>1080]+bestaudio/bestvideo[vcodec^=avc]+bestaudio[acodec^=mp4a]/bestvideo+bestaudio/best"
                     ])
                     cmd.extend(['--merge-output-format', 'mp4'])
                     
                 elif target == 'webm':
                     # Prioritize vp9/av1 + opus/vorbis
                     cmd.extend(['-f', "bestvideo[vcodec^=vp9]+bestaudio[acodec^=opus]/bestvideo[ext=webm]+bestaudio[ext=webm]/best[ext=webm]/best"])
                     cmd.extend(['--merge-output-format', 'webm'])
                     
                 else:
                     # MKV or others: just get best
                     cmd.extend(['--merge-output-format', target])
            else:
                # No specific target, just best
                pass
        else:
            # Transcoding Mode: Use defaults and transcode later
            if self.audio_only:
                 audio_fmt = self.target_ext if self.target_ext else 'mp3'
                 cmd.extend(['-x', '--audio-format', audio_fmt])
            else:
                 if self.target_ext:
                    cmd.extend(['--merge-output-format', self.target_ext])

        # Auth
        if self.cookies:
            if self.cookies.startswith("browser:"):
                browser = self.cookies.split(":")[1]
                cmd.extend(['--cookies-from-browser', browser])
            elif self.cookies.startswith("file:"):
                file_path = self.cookies.split(":", 1)[1]
                cmd.extend(['--cookies', file_path])
        
        # JS runtime
        if js_runtime and os.path.isabs(js_runtime): 
            if "deno" in os.path.basename(js_runtime).lower():
                 cmd.extend(['--js-runtimes', f"deno:{js_runtime}"])
        
        if ffmpeg_path:
             cmd.extend(['--ffmpeg-location', os.path.dirname(ffmpeg_path)])

        cmd.extend([self.url])
        
        self.logger.debug(f"Command: {' '.join(cmd)}")
        self.log_message.emit(f"Command constructed.")
        
        final_filename = None
        skipped = False
        
        try:
            self.process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, 
                text=True, 
                encoding=encoding,
                errors='replace',
                startupinfo=startupinfo
            )
            
            # Read Output
            while self.is_running:
                line = self.process.stdout.readline()
                if not line:
                    if self.process.poll() is not None:
                        break
                    continue
                
                line = line.strip()
                if not line: continue
                
                self.logger.debug(f"[yt-dlp] {line}")
                
                # Check for skipped
                if "has already been downloaded" in line or "Video already in the database" in line:
                    skipped = True
                    self.log_message.emit("File already exists. Skipping.")
                
                # Parse
                if '[download]' in line and '%' in line:
                    self.parse_progress(line)
                elif 'Destination:' in line or 'Already downloaded:' in line or 'Merging formats into' in line:
                     parts = line.split(':', 1)
                     if len(parts) > 1:
                         fname = parts[1].strip().strip('"')
                         if not os.path.isabs(fname):
                             fname = os.path.join(self.download_path, fname)
                         final_filename = fname
                         self.current_filename = fname
                         self.log_message.emit(f"Target File: {final_filename}")
                     self.log_message.emit(line)
                else:
                    self.log_message.emit(line)

            rc = self.process.poll()
            
            if skipped:
                self.progress_update.emit(100, "Done (Skipped)", "")
                self.log_message.emit("Download skipped (File exists).")
                self.finished.emit()
                return

            if rc == 0:
                self.progress_update.emit(100, "Done", "00:00")
                self.log_message.emit("Download finished.")
            else:
                if not self.is_running: # Cancelled
                    return
                self.error_occurred.emit(f"Download process failed with code {rc}")
                self.logger.error(f"yt-dlp failed with code {rc}")
                return

            # --- Post Processing (Transcoding) ---
            should_transcode = self.codec and self.codec != "변환 없음" and self.codec != "None" and not self.audio_only
            
            if should_transcode and final_filename and os.path.exists(final_filename):
                self.perform_transcode(final_filename, ffmpeg_path, encoding, startupinfo)
            else:
                self.finished.emit()
                
        except Exception as e:
            if self.is_running: # Only emit error if not cancelled
                self.logger.exception("Error in start_download")
                self.error_occurred.emit(f"An error occurred: {str(e)}")
        finally:
            self.is_running = False
            self.process = None

    def perform_transcode(self, final_filename, ffmpeg_path, encoding, startupinfo):
        self.log_message.emit(f"Starting Post-Process: {self.codec} (Threads: {self.threads})")
        self.progress_update.emit(0, "Encoding...", "Calculating...")

        base, ext = os.path.splitext(final_filename)
        input_file = f"{base}_raw{ext}"
        try:
            if os.path.exists(input_file):
                os.remove(input_file)
            os.rename(final_filename, input_file)
            self.current_filename = input_file # Track temp file for cleanup
        except OSError as e:
            self.error_occurred.emit(f"File rename failed: {e}")
            return

        # Get Duration
        duration_sec = 0
        try:
                probe_cmd = [ffmpeg_path, '-i', input_file]
                probe_process = subprocess.run(
                probe_cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                text=True, 
                encoding=encoding,
                errors='replace',
                startupinfo=startupinfo
            )
                match = re.search(r'Duration: (\d{2}):(\d{2}):(\d{2}\.\d{2})', probe_process.stderr)
                if match:
                    h, m, s = match.groups()
                    duration_sec = float(h)*3600 + float(m)*60 + float(s)
        except Exception:
            pass

        # Build FFmpeg Command
        ffmpeg_cmd = [ffmpeg_path, '-y']
        
        # Threads (Input Decoding - Helps feeding GPU)
        if self.threads > 1:
            ffmpeg_cmd.extend(['-threads', str(self.threads)])
            
        ffmpeg_cmd.extend(['-i', input_file])
        
        # Threads (Output Encoding - mostly for CPU encoders, but harmless for NVENC)
        # Note: Some encoders verify thread count differently, but global -threads usually covers decoders.
        # We add it again for the encoder if needed, but usually input is the bottleneck for NVENC.
        # Let's keep it simple: Global threads is usually enough.
        
        # Map Codec & Preset
        c_args = []
        if "H264 (CPU)" in self.codec:
            c_args = ['-c:v', 'libx264']
            if "무손실" in self.preset: c_args.extend(['-crf', '0', '-preset', 'ultrafast'])
            elif "최소 손실" in self.preset: c_args.extend(['-crf', '17', '-preset', 'slow'])
            elif "최대 압축" in self.preset: c_args.extend(['-crf', '28', '-preset', 'veryslow'])
            else: c_args.extend(['-crf', '23', '-preset', 'medium'])
            
        elif "NVENC" in self.codec:
            c_args = ['-c:v', 'h264_nvenc']
            if "무손실" in self.preset: c_args.extend(['-preset', 'p7', '-rc', 'constqp', '-qp', '0']) 
            elif "최소 손실" in self.preset: c_args.extend(['-preset', 'p6', '-cq', '19', '-rc', 'vbr_hq'])
            elif "최대 압축" in self.preset: c_args.extend(['-preset', 'p7', '-cq', '30', '-rc', 'vbr_hq'])
            else: c_args.extend(['-preset', 'p4', '-b:v', '5M']) 
            
        elif "HEVC" in self.codec:
            c_args = ['-c:v', 'libx265']
            if "무손실" in self.preset: c_args.extend(['-x265-params', 'lossless=1'])
            elif "최소 손실" in self.preset: c_args.extend(['-crf', '20', '-preset', 'slow'])
            elif "최대 압축" in self.preset: c_args.extend(['-crf', '30', '-preset', 'veryslow'])
            else: c_args.extend(['-crf', '26', '-preset', 'medium'])
            
        elif "VP9" in self.codec:
            c_args = ['-c:v', 'libvpx-vp9']
            if "무손실" in self.preset: c_args.extend(['-lossless', '1'])
            elif "최소 손실" in self.preset: c_args.extend(['-crf', '15', '-b:v', '0'])
            elif "최대 압축" in self.preset: c_args.extend(['-crf', '40', '-b:v', '0'])
            else: c_args.extend(['-crf', '30', '-b:v', '0'])

        ffmpeg_cmd.extend(c_args)
        ffmpeg_cmd.extend(['-c:a', 'copy', final_filename])
        
        self.logger.debug(f"Encoding command: {' '.join(ffmpeg_cmd)}")

        self.process = subprocess.Popen(
            ffmpeg_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding=encoding,
            errors='replace',
            startupinfo=startupinfo
        )
        
        while self.is_running:
            line = self.process.stdout.readline()
            if not line:
                if self.process.poll() is not None:
                    break
                continue
            
            line = line.strip()
            # Parse Progress
            if duration_sec > 0 and "time=" in line:
                match = re.search(r'time=(\d{2}):(\d{2}):(\d{2}\.\d{2})', line)
                if match:
                    h, m, s = match.groups()
                    current_sec = float(h)*3600 + float(m)*60 + float(s)
                    percent = (current_sec / duration_sec) * 100
                    self.progress_update.emit(percent, "Encoding", "")

        if self.process.returncode == 0:
            self.log_message.emit("Encoding completed.")
            self.progress_update.emit(100, "Done", "")
            try: os.remove(input_file)
            except: pass
            self.finished.emit()
        else:
             if self.is_running:
                self.error_occurred.emit(f"Encoding failed: {self.process.returncode}")
                # Restore
                if os.path.exists(input_file) and not os.path.exists(final_filename):
                    os.rename(input_file, final_filename)

    def parse_progress(self, line):
        try:
            parts = line.split()
            percent_str = parts[1].replace('%','')
            speed_str = parts[5]
            eta_str = parts[7]
            self.progress_update.emit(float(percent_str), speed_str, eta_str)
        except:
            pass

    def stop(self):
        self.is_running = False
        self.log_message.emit("Stopping process...")
        
        # Kill Process
        if self.process:
            try:
                self.process.terminate() # Try soft kill
                self.process.wait(timeout=2)
            except:
                try: self.process.kill() # Hard kill
                except: pass
        
        # Cleanup
        if self.current_filename:
             base = os.path.splitext(self.current_filename)[0]
             # Clean up .part, .ytdl, _raw files
             cleanup_patterns = [
                 f"{self.current_filename}.part",
                 f"{self.current_filename}.ytdl",
                 f"{base}.part",
                 f"{base}.ytdl",
                 f"{base}_raw*"
             ]
             
             for pattern in cleanup_patterns:
                 for f in glob.glob(pattern):
                     try: os.remove(f); self.logger.debug(f"Deleted cleanup: {f}")
                     except: pass

class DownloaderThread(QThread):
    def __init__(self, downloader):
        super().__init__()
        self.downloader = downloader

    def run(self):
        self.downloader.start_download()
