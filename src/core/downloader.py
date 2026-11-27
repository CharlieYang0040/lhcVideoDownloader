import collections
import datetime
import glob
import json
import locale
import logging
import os
import re
import subprocess
import tempfile
import threading
import time
import urllib.request
import uuid
from PySide6.QtCore import QObject, Signal, QThread, Qt
from src.utils.helpers import (
    check_js_runtime,
    create_startupinfo,
    get_lib_path,
    get_logs_dir,
    terminate_process_tree,
)


def retry_file_op(op, retries=10, delay=0.3):
    last_error = None
    for attempt in range(retries):
        try:
            return op()
        except (PermissionError, OSError) as e:
            last_error = e
            if attempt == retries - 1:
                raise
            time.sleep(delay)
    if last_error:
        raise last_error


class YtDlpUpdateThread(QThread):
    """Checks and updates yt-dlp once on application startup."""

    status_changed = Signal(str)
    log_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger(self.__class__.__name__)
        self._stop_event = threading.Event()
        self._process = None

    def stop(self):
        self._stop_event.set()
        terminate_process_tree(self._process, self.logger)

    @staticmethod
    def _get_version(yt_dlp_path, encoding, startupinfo):
        try:
            result = subprocess.run(
                [yt_dlp_path, '--version'],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding=encoding,
                errors='replace',
                startupinfo=startupinfo,
                timeout=20,
            )
        except (OSError, subprocess.SubprocessError):
            return None

        if result.returncode != 0:
            return None

        lines = [line.strip() for line in (result.stdout or '').splitlines() if line.strip()]
        return lines[-1] if lines else None

    @staticmethod
    def _fetch_latest_release_info(timeout=10):
        req = urllib.request.Request(
            "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest",
            headers={"User-Agent": "LHCVideoDownloader"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        tag_name = (data.get("tag_name") or "").strip()
        target_asset = "yt-dlp.exe" if os.name == "nt" else "yt-dlp"
        download_url = None
        for asset in data.get("assets", []):
            if asset.get("name") == target_asset:
                download_url = asset.get("browser_download_url")
                break
        return tag_name, download_url

    def _download_and_replace_ytdlp(self, download_url, yt_dlp_path, encoding, startupinfo):
        temp_path = yt_dlp_path + ".new"
        try:
            req = urllib.request.Request(download_url, headers={"User-Agent": "LHCVideoDownloader"})
            with urllib.request.urlopen(req, timeout=120) as resp, open(temp_path, "wb") as out_f:
                while True:
                    if self._stop_event.is_set():
                        raise RuntimeError("Update cancelled")
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    out_f.write(chunk)

            if not os.path.isfile(temp_path) or os.path.getsize(temp_path) == 0:
                raise RuntimeError("Downloaded yt-dlp binary is empty")

            new_version = self._get_version(temp_path, encoding, startupinfo)
            if not new_version:
                raise RuntimeError("Downloaded yt-dlp binary failed verification")

            retry_file_op(lambda: os.replace(temp_path, yt_dlp_path), retries=10, delay=0.3)
            return new_version
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    def run(self):
        yt_dlp_path = get_lib_path('yt-dlp')
        if not yt_dlp_path or not os.path.exists(yt_dlp_path):
            self.status_changed.emit("yt-dlp 없음")
            return

        encoding = locale.getpreferredencoding()
        startupinfo = create_startupinfo()

        with VideoDownloader._yt_dlp_update_lock:
            if self._stop_event.is_set():
                return

            self.status_changed.emit("yt-dlp 업데이트 확인 중...")
            current_version = self._get_version(yt_dlp_path, encoding, startupinfo)
            if current_version:
                self.logger.info(f"yt-dlp current version: {current_version}")
                self.log_message.emit(f"yt-dlp current version: {current_version}")

            if self._stop_event.is_set():
                return

            # Prefer GitHub API + atomic binary replacement to avoid Windows self-update lock race
            try:
                latest_tag, download_url = self._fetch_latest_release_info(timeout=10)
                if self._stop_event.is_set():
                    return

                if current_version and latest_tag and latest_tag == current_version:
                    VideoDownloader._yt_dlp_last_version = current_version
                    VideoDownloader._yt_dlp_update_checked = True
                    self.logger.info(f"yt-dlp is up to date ({current_version}).")
                    self.log_message.emit(f"yt-dlp is up to date ({current_version}).")
                    self.status_changed.emit(f"yt-dlp 최신 ({current_version})")
                    return

                if latest_tag and download_url and os.access(os.path.dirname(os.path.abspath(yt_dlp_path)), os.W_OK):
                    self.status_changed.emit(f"yt-dlp 업데이트 중 ({current_version or '?'} → {latest_tag})...")
                    self.logger.info(f"Updating yt-dlp directly: {current_version} -> {latest_tag}")
                    new_version = self._download_and_replace_ytdlp(download_url, yt_dlp_path, encoding, startupinfo)
                    VideoDownloader._yt_dlp_last_version = new_version
                    VideoDownloader._yt_dlp_update_checked = True
                    msg = (
                        f"yt-dlp updated: {current_version} -> {new_version}"
                        if current_version
                        else f"yt-dlp updated to {new_version}"
                    )
                    self.logger.info(msg)
                    self.log_message.emit(msg)
                    if current_version and new_version != current_version:
                        self.status_changed.emit(f"yt-dlp 업데이트 완료 ({current_version} → {new_version})")
                    else:
                        self.status_changed.emit(f"yt-dlp 최신 ({new_version})")
                    return
            except Exception as api_err:
                if self._stop_event.is_set():
                    return
                self.logger.warning(f"Direct yt-dlp update failed ({api_err}), falling back to yt-dlp -U")
                self.log_message.emit(f"Direct yt-dlp update check failed ({api_err}); falling back to yt-dlp -U.")

            rc = None
            update_process = None
            try:
                update_process = subprocess.Popen(
                    [yt_dlp_path, '-U'],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding=encoding,
                    errors='replace',
                    startupinfo=startupinfo,
                )
                self._process = update_process
                try:
                    output, _ = update_process.communicate(timeout=120)
                except subprocess.TimeoutExpired:
                    terminate_process_tree(update_process, self.logger)
                    output, _ = update_process.communicate()
                    self.logger.warning("yt-dlp startup update timed out.")
                    self.log_message.emit("yt-dlp startup update timed out.")
                    output = output or ""
                rc = update_process.returncode
                for line in (output or '').splitlines():
                    line = line.strip()
                    if line:
                        self.logger.info(f"[yt-dlp startup update] {line}")
                        self.log_message.emit(f"[yt-dlp update] {line}")
            except Exception as e:
                self.logger.warning("yt-dlp startup update failed", exc_info=True)
                self.log_message.emit(f"yt-dlp update failed: {e}")
            finally:
                self._process = None

            if self._stop_event.is_set():
                return

            # Allow detached Windows yt-dlp -U cmd helper to finish replacing exe
            if os.name == "nt":
                time.sleep(1.5)

            latest_version = self._get_version(yt_dlp_path, encoding, startupinfo)
            VideoDownloader._yt_dlp_last_version = latest_version or current_version
            VideoDownloader._yt_dlp_update_checked = True

            if current_version and latest_version and latest_version != current_version:
                self.status_changed.emit(f"yt-dlp 업데이트 완료 ({current_version} → {latest_version})")
            elif rc == 0 and latest_version:
                self.status_changed.emit(f"yt-dlp 최신 ({latest_version})")
            elif latest_version or current_version:
                ver = latest_version or current_version
                self.status_changed.emit(f"yt-dlp {ver} (업데이트 확인 실패)")
            else:
                self.status_changed.emit("yt-dlp 업데이트 확인 실패")


class VideoDownloader(QObject):
    """
    Wrapper for yt-dlp and ffmpeg execution.
    Emits signals for progress, status, and logs.
    """
    progress_update = Signal(float, str, str)  # progress %, speed, eta
    log_message = Signal(str)
    status_update = Signal(str)
    finished = Signal()
    error_occurred = Signal(str)
    auth_required = Signal(str)

    AUTH_ERROR_PATTERNS = (
        "sign in to confirm your age",
        "confirm your age",
        "age-restricted",
        "sign in to confirm you're not a bot",
        "sign in to confirm you\u2019re not a bot",
        "members-only",
        "available to this channel's members",
        "join this channel to get access",
        "login required",
        "use --cookies-from-browser or --cookies",
        "private video",
    )

    _yt_dlp_update_lock = threading.Lock()
    _yt_dlp_update_checked = False
    _yt_dlp_last_version = None

    def __init__(self, url, path, audio_only, cookies, codec, preset, target_ext, overwrite=False, threads=1, fragments=5, fallback_cookies=None):
        super().__init__()
        self.url = url
        self.download_path = path
        self.audio_only = audio_only
        self.cookies = cookies
        self.fallback_cookies = fallback_cookies
        self.codec = codec
        self.preset = preset
        self.target_ext = target_ext
        self.overwrite = overwrite
        self.threads = threads
        self.fragments = fragments

        self.is_running = False
        self._cancelled = False
        self.process = None
        self.current_filename = None
        self.tracked_files = []
        self.log_file_path = None
        self._task_log_handle = None
        self._log_lock = threading.Lock()
        self.logger = logging.getLogger(self.__class__.__name__)

        self.log_message.connect(self._write_task_log, Qt.DirectConnection)
        self.error_occurred.connect(lambda msg: self._write_task_log(f"ERROR: {msg}"), Qt.DirectConnection)
        self.auth_required.connect(lambda msg: self._write_task_log(f"AUTH REQUIRED: {msg}"), Qt.DirectConnection)

    def _open_task_log(self):
        self._close_task_log()
        try:
            tasks_dir = get_logs_dir("tasks")
            os.makedirs(tasks_dir, exist_ok=True)
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            short_id = uuid.uuid4().hex[:6]
            self.log_file_path = os.path.join(tasks_dir, f"{timestamp}_{short_id}.log")
            self._task_log_handle = open(self.log_file_path, "w", encoding="utf-8", errors="replace")
            self._task_log_handle.write(
                f"URL: {self.url}\n"
                f"Download Path: {self.download_path}\n"
                f"Options: AudioOnly={self.audio_only}, Ext={self.target_ext}, Codec={self.codec}, Preset={self.preset}, Overwrite={self.overwrite}, Threads={self.threads}, Fragments={self.fragments}\n"
                f"Started: {datetime.datetime.now().isoformat()}\n"
                + ("-" * 60)
                + "\n"
            )
            self._task_log_handle.flush()
            self._prune_task_logs(tasks_dir, keep=50)
        except OSError as e:
            self.logger.debug(f"Could not open task log file: {e}")
            self._task_log_handle = None

    @staticmethod
    def _prune_task_logs(tasks_dir, keep=50):
        try:
            entries = [
                os.path.join(tasks_dir, name)
                for name in os.listdir(tasks_dir)
                if name.endswith(".log")
            ]
            if len(entries) <= keep:
                return
            entries.sort(key=lambda p: os.path.getmtime(p))
            for old_path in entries[:-keep]:
                try:
                    os.remove(old_path)
                except OSError:
                    pass
        except OSError:
            pass

    def _write_task_log(self, message):
        with self._log_lock:
            if self._task_log_handle is None:
                return
            try:
                ts = datetime.datetime.now().strftime("%H:%M:%S")
                self._task_log_handle.write(f"[{ts}] {message}\n")
                self._task_log_handle.flush()
            except OSError:
                pass

    def _close_task_log(self):
        with self._log_lock:
            if self._task_log_handle is not None:
                try:
                    self._task_log_handle.flush()
                    self._task_log_handle.close()
                except OSError:
                    pass
                self._task_log_handle = None

    @staticmethod
    def create_startupinfo():
        return create_startupinfo()

    def set_cookies(self, cookies, fallback_cookies=None):
        self.cookies = cookies
        self.fallback_cookies = fallback_cookies

    @classmethod
    def is_auth_error_line(cls, line):
        lower = line.lower()
        return any(pattern in lower for pattern in cls.AUTH_ERROR_PATTERNS)

    def _track_file(self, path):
        if not path:
            return
        norm = os.path.normpath(path)
        if norm not in self.tracked_files:
            self.tracked_files.append(norm)

    def wait_for_startup_update(self):
        downloader_type = type(self)
        if not downloader_type._yt_dlp_update_lock.locked():
            return True

        self.status_update.emit("업데이트 대기")
        self.log_message.emit("Waiting for startup yt-dlp update check to finish...")
        while self.is_running:
            if downloader_type._yt_dlp_update_lock.acquire(timeout=0.2):
                downloader_type._yt_dlp_update_lock.release()
                return True
        return False

    def resolve_output_path(self, filename):
        filename = filename.strip().strip('"')
        if not filename:
            return None

        if not os.path.isabs(filename):
            filename = os.path.join(self.download_path, filename)
        return os.path.normpath(filename)

    def parse_output_filename(self, line):
        quoted_patterns = (
            r'Merging formats into\s+"([^"]+)"',
            r'Destination:\s+"([^"]+)"',
            r'Already downloaded:\s+"([^"]+)"',
        )
        for pattern in quoted_patterns:
            match = re.search(pattern, line)
            if match:
                return self.resolve_output_path(match.group(1))

        plain_patterns = (
            r'Destination:\s+(.+)$',
            r'Already downloaded:\s+(.+)$',
            r'^\[download\]\s+(.+?)\s+has already been downloaded',
        )
        for pattern in plain_patterns:
            match = re.search(pattern, line)
            if match:
                return self.resolve_output_path(match.group(1))

        return None

    @staticmethod
    def parse_timestamp_seconds(value):
        match = re.match(r'(\d+):(\d{2}):(\d{2}(?:\.\d+)?)', value)
        if not match:
            return None

        h, m, s = match.groups()
        return (float(h) * 3600) + (float(m) * 60) + float(s)

    def emit_encoding_progress(self, current_sec, duration_sec):
        if duration_sec <= 0:
            return

        percent = max(0, min((current_sec / duration_sec) * 100, 100))
        self.progress_update.emit(percent, "Encoding", "")

    def _read_recorded_files(self, meta_file_path, encoding):
        if not meta_file_path or not os.path.exists(meta_file_path):
            return []

        raw_lines = []
        for enc in ('utf-8-sig', encoding):
            try:
                with open(meta_file_path, 'r', encoding=enc, errors='replace') as f:
                    raw_lines = f.read().splitlines()
                break
            except OSError:
                return []
            except UnicodeError:
                continue

        resolved = []
        seen = set()
        for line in raw_lines:
            candidate = self.resolve_output_path(line)
            if not candidate:
                continue
            key = os.path.normcase(candidate)
            if key in seen or not os.path.exists(candidate):
                continue
            seen.add(key)
            resolved.append(candidate)
            self._track_file(candidate)
        return resolved

    def _build_ytdlp_command(self, yt_dlp_path, ffmpeg_path, js_runtime, meta_file_path, should_transcode, active_cookies):
        cmd = [
            yt_dlp_path,
            '--newline',
            '--no-simulate',
            '--file-access-retries', '10',
            '--print-to-file', 'after_move:%(filepath)s', meta_file_path.replace('%', '%%'),
            '-o', os.path.join(self.download_path, '%(title)s.%(ext)s'),
        ]

        if not self.overwrite:
            cmd.append('--no-overwrites')
        else:
            cmd.append('--force-overwrites')

        if self.fragments > 1:
            cmd.extend(['-N', str(self.fragments)])

        if not should_transcode:
            if self.audio_only:
                audio_fmt = self.target_ext if self.target_ext else 'mp3'
                cmd.extend(['-f', f"bestaudio[ext={audio_fmt}]/bestaudio/best"])
                cmd.extend(['-x', '--audio-format', audio_fmt])
            elif self.target_ext:
                target = self.target_ext.lower()
                if target == 'mp4':
                    cmd.extend([
                        '-f',
                        "bestvideo[height>1080]+bestaudio[ext=m4a]/bestvideo[height>1080]+bestaudio/"
                        "bestvideo[vcodec^=avc]+bestaudio[acodec^=mp4a]/"
                        "bestvideo+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
                    ])
                    cmd.extend(['--merge-output-format', 'mp4'])
                elif target == 'webm':
                    cmd.extend([
                        '-f',
                        "bestvideo[vcodec^=vp9]+bestaudio[acodec^=opus]/"
                        "bestvideo[ext=webm]+bestaudio[ext=webm]/best[ext=webm]/best",
                    ])
                    cmd.extend(['--merge-output-format', 'webm/mkv'])
                else:
                    cmd.extend(['--merge-output-format', target])
        else:
            if self.target_ext:
                target = self.target_ext.lower()
                merge_fmt = f"{target}/mkv" if target != "mkv" else "mkv"
                cmd.extend(['--merge-output-format', merge_fmt])
            else:
                cmd.extend(['--merge-output-format', 'mkv'])

        if active_cookies:
            if active_cookies.startswith("browser:"):
                browser = active_cookies.split(":", 1)[1]
                cmd.extend(['--cookies-from-browser', browser])
            elif active_cookies.startswith("file:"):
                file_path = active_cookies.split(":", 1)[1]
                cmd.extend(['--cookies', file_path])

        if js_runtime == "node":
            cmd.extend(['--js-runtimes', 'node'])
        elif js_runtime == "deno":
            cmd.extend(['--js-runtimes', 'deno'])
        elif js_runtime and os.path.isabs(js_runtime):
            basename = os.path.basename(js_runtime).lower()
            if "deno" in basename:
                cmd.extend(['--js-runtimes', f"deno:{js_runtime}"])
            elif "node" in basename:
                cmd.extend(['--js-runtimes', f"node:{js_runtime}"])

        if ffmpeg_path:
            cmd.extend(['--ffmpeg-location', os.path.dirname(ffmpeg_path)])

        cmd.append(self.url)
        return cmd

    def _run_ytdlp_attempt(self, cmd, encoding, startupinfo):
        final_filename = None
        saw_already_downloaded = False
        did_download_or_postprocess = False
        did_merge = False
        auth_error_detected = False
        last_error_line = None
        failed_delete_files = []

        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding=encoding,
            errors='replace',
            startupinfo=startupinfo,
        )

        while self.is_running:
            line = self.process.stdout.readline()
            if not line:
                if self.process.poll() is not None:
                    break
                continue

            line = line.strip()
            if not line:
                continue

            self.logger.debug(f"[yt-dlp] {line}")

            if line.startswith("ERROR:") or "ERROR:" in line:
                last_error_line = line
            if self.is_auth_error_line(line):
                auth_error_detected = True

            unable_delete_match = re.search(r'WARNING:\s+Unable to delete file\s+(.+)$', line)
            if unable_delete_match:
                leftover = self.resolve_output_path(unable_delete_match.group(1))
                if leftover and leftover not in failed_delete_files:
                    failed_delete_files.append(leftover)

            if '[Merger] Merging formats into' in line or 'Merging formats into' in line:
                did_download_or_postprocess = True
                did_merge = True
                self.status_update.emit("병합 중")
                parsed_filename = self.parse_output_filename(line)
                if parsed_filename:
                    final_filename = parsed_filename
                    self.current_filename = parsed_filename
                    self._track_file(parsed_filename)
                    self.log_message.emit(f"Target File: {final_filename}")
                self.log_message.emit(line)
            elif (
                '[ExtractAudio]' in line
                or '[VideoRemuxer]' in line
                or '[VideoConvertor]' in line
                or '[Fixup' in line
            ):
                did_download_or_postprocess = True
                self.status_update.emit("후처리 중")
                self.log_message.emit(line)
            elif '[download]' in line and '%' in line:
                did_download_or_postprocess = True
                self.parse_progress(line)
            elif 'has already been downloaded' in line or 'Video already in the database' in line:
                saw_already_downloaded = True
                parsed_filename = self.parse_output_filename(line)
                if parsed_filename:
                    final_filename = parsed_filename
                    self.current_filename = parsed_filename
                    self._track_file(parsed_filename)
                self.log_message.emit(line)
            elif 'Destination:' in line:
                did_download_or_postprocess = True
                parsed_filename = self.parse_output_filename(line)
                if parsed_filename:
                    final_filename = parsed_filename
                    self.current_filename = parsed_filename
                    self._track_file(parsed_filename)
                    self.log_message.emit(f"Target File: {final_filename}")
                self.log_message.emit(line)
            elif 'Already downloaded:' in line:
                saw_already_downloaded = True
                parsed_filename = self.parse_output_filename(line)
                if parsed_filename:
                    final_filename = parsed_filename
                    self.current_filename = parsed_filename
                    self._track_file(parsed_filename)
                self.log_message.emit(line)
            else:
                self.log_message.emit(line)

        if not self.is_running:
            terminate_process_tree(self.process, self.logger)
            return None, final_filename, saw_already_downloaded, did_download_or_postprocess, did_merge, auth_error_detected, last_error_line, failed_delete_files

        rc = self.process.wait()
        return rc, final_filename, saw_already_downloaded, did_download_or_postprocess, did_merge, auth_error_detected, last_error_line, failed_delete_files

    def _cleanup_post_merge_files(self, final_files, failed_delete_files, did_merge):
        final_norm_set = {
            os.path.normcase(os.path.normpath(p))
            for p in final_files
            if p
        }
        candidates = []
        seen = set()

        def add_candidate(path):
            if not path:
                return
            norm = os.path.normcase(os.path.normpath(path))
            if norm in final_norm_set or norm in seen:
                return
            seen.add(norm)
            candidates.append(path)

        for path in failed_delete_files:
            add_candidate(path)

        if did_merge:
            for final_file in final_files:
                base = os.path.splitext(final_file)[0]
                for match_path in glob.glob(f"{glob.escape(base)}.f*"):
                    suffix = match_path[len(base):]
                    if re.match(r'^\.f[0-9A-Za-z_-]+\.[0-9A-Za-z]+$', suffix):
                        add_candidate(match_path)

        for path in candidates:
            if not os.path.exists(path):
                continue
            try:
                retry_file_op(lambda p=path: os.remove(p), retries=10, delay=0.5)
                self.log_message.emit(f"Cleaned up leftover temp file: {path}")
            except OSError as e:
                self.logger.warning(f"Could not clean up leftover temp file {path}: {e}")
                self.log_message.emit(f"WARNING: Leftover temp file could not be deleted: {path}")

    def start_download(self):
        self.is_running = True
        self._cancelled = False
        self.tracked_files = []
        self.current_filename = None
        self._open_task_log()
        self.logger.debug(f"Starting download for URL: {self.url}")
        self.logger.debug(f"Options: Audio={self.audio_only}, Codec={self.codec}, Ext={self.target_ext}, Overwrite={self.overwrite}")

        yt_dlp_path = get_lib_path('yt-dlp')
        ffmpeg_path = get_lib_path('ffmpeg')

        if not yt_dlp_path or not os.path.exists(yt_dlp_path):
            self.error_occurred.emit("yt-dlp.exe not found.")
            self._close_task_log()
            self.is_running = False
            return

        if not ffmpeg_path or not os.path.exists(ffmpeg_path):
            self.error_occurred.emit("ffmpeg.exe not found. FFmpeg is required for merging, audio extraction, and encoding.")
            self._close_task_log()
            self.is_running = False
            return

        js_runtime = check_js_runtime()
        if not js_runtime:
            self.error_occurred.emit("Javascript runtime not found. Deno or Node.js is required.")
            self._close_task_log()
            self.is_running = False
            return

        if not self.wait_for_startup_update():
            self._close_task_log()
            self.is_running = False
            return

        encoding = locale.getpreferredencoding()
        startupinfo = create_startupinfo()

        meta_file_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode='w',
                prefix='lhcvd_files_',
                suffix='.txt',
                delete=False,
                encoding='utf-8',
            ) as tmp:
                meta_file_path = tmp.name

            should_transcode = bool(
                self.codec and self.codec not in ("변환 없음", "None") and not self.audio_only
            )

            active_cookies = self.cookies
            retried_with_fallback = False

            while True:
                with open(meta_file_path, 'w', encoding='utf-8') as f:
                    f.truncate(0)

                cmd = self._build_ytdlp_command(
                    yt_dlp_path,
                    ffmpeg_path,
                    js_runtime,
                    meta_file_path,
                    should_transcode,
                    active_cookies,
                )

                self.logger.debug(f"Command: {' '.join(cmd)}")
                self.log_message.emit("Command constructed.")
                if not retried_with_fallback:
                    self.status_update.emit("다운로드 중")

                (
                    rc,
                    final_filename,
                    saw_already_downloaded,
                    did_download_or_postprocess,
                    did_merge,
                    auth_error_detected,
                    last_error_line,
                    failed_delete_files,
                ) = self._run_ytdlp_attempt(cmd, encoding, startupinfo)

                if not self.is_running or rc is None:
                    self.cleanup_temp_files()
                    return

                if rc == 0:
                    break

                if auth_error_detected:
                    if active_cookies is None and self.fallback_cookies and not retried_with_fallback:
                        retried_with_fallback = True
                        active_cookies = self.fallback_cookies
                        self.log_message.emit("성인 인증/로그인 필요 영상 감지 — 저장된 인증으로 자동 재시도합니다...")
                        self.status_update.emit("인증 재시도")
                        continue

                    if active_cookies:
                        reason_msg = "저장된 쿠키가 만료되었거나 인증 권한이 부족합니다. 다시 로그인해주세요."
                    else:
                        reason_msg = "성인 인증 또는 로그인이 필요한 영상입니다. 로그인 후 다시 시도해주세요."
                    if last_error_line:
                        self.logger.warning(f"Auth error detected: {last_error_line}")
                    self.auth_required.emit(reason_msg)
                    self.error_occurred.emit(reason_msg)
                    return

                self.error_occurred.emit(f"Download process failed with code {rc}")
                self.logger.error(f"yt-dlp failed with code {rc}")
                return

            final_files = self._read_recorded_files(meta_file_path, encoding)
            if not final_files and final_filename and os.path.exists(final_filename):
                final_files = [final_filename]

            if did_merge or failed_delete_files:
                self._cleanup_post_merge_files(final_files, failed_delete_files, did_merge)

            if saw_already_downloaded and not did_download_or_postprocess:
                self.progress_update.emit(100, "Done (Skipped)", "")
                self.log_message.emit("Download skipped (File exists).")
                self.finished.emit()
                return

            if should_transcode:
                if not final_files:
                    if not final_filename:
                        self.error_occurred.emit("Downloaded file name could not be determined. Encoding cannot start.")
                    else:
                        self.error_occurred.emit(f"Downloaded file not found for encoding: {final_filename}")
                    return

                for filepath in final_files:
                    if not self.is_running:
                        self.cleanup_temp_files()
                        return
                    if not self.perform_transcode(filepath, ffmpeg_path, encoding, startupinfo):
                        return

                self.finished.emit()
            else:
                self.progress_update.emit(100, "Done", "00:00")
                self.log_message.emit("Download finished.")
                self.finished.emit()

        except Exception as e:
            if self.is_running:
                self.logger.exception("Error in start_download")
                self.error_occurred.emit(f"An error occurred: {str(e)}")
        finally:
            if meta_file_path and os.path.exists(meta_file_path):
                try:
                    os.remove(meta_file_path)
                except OSError:
                    pass
            self._close_task_log()
            self.is_running = False
            self.process = None

    def _probe_media_info(self, source_file, ffmpeg_path, encoding, startupinfo):
        duration_sec = 0.0
        source_audio_codec = None
        try:
            probe_process = subprocess.run(
                [ffmpeg_path, '-i', source_file],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding=encoding,
                errors='replace',
                startupinfo=startupinfo,
                timeout=30,
            )
            stderr_text = probe_process.stderr or ""
            dur_match = re.search(r'Duration:\s*(\d+:\d{2}:\d{2}(?:\.\d+)?)', stderr_text)
            if dur_match:
                duration_sec = self.parse_timestamp_seconds(dur_match.group(1)) or 0.0

            audio_match = re.search(r'Audio:\s*([a-zA-Z0-9_]+)', stderr_text)
            if audio_match:
                source_audio_codec = audio_match.group(1).lower()
        except Exception as e:
            self.logger.debug(f"Media probe failed for {source_file}: {e}")
        return duration_sec, source_audio_codec

    def _select_audio_args(self, output_ext, source_audio_codec):
        ext = output_ext.lower()
        if ext == '.mp4':
            if source_audio_codec in ('aac', 'mp3', 'ac3', 'eac3', 'alac'):
                return ['-c:a', 'copy']
            return ['-c:a', 'aac', '-b:a', '192k']
        if ext == '.webm':
            if source_audio_codec in ('opus', 'vorbis'):
                return ['-c:a', 'copy']
            return ['-c:a', 'libopus', '-b:a', '192k']
        return ['-c:a', 'copy']

    def _select_video_args(self):
        if "H264 (CPU)" in self.codec:
            args = ['-c:v', 'libx264']
            if "무손실" in self.preset:
                args.extend(['-crf', '0', '-preset', 'ultrafast'])
            elif "최소 손실" in self.preset:
                args.extend(['-crf', '17', '-preset', 'slow', '-pix_fmt', 'yuv420p'])
            elif "최대 압축" in self.preset:
                args.extend(['-crf', '28', '-preset', 'veryslow', '-pix_fmt', 'yuv420p'])
            else:
                args.extend(['-crf', '23', '-preset', 'medium', '-pix_fmt', 'yuv420p'])
            return args

        if "NVENC" in self.codec:
            args = ['-c:v', 'h264_nvenc']
            if "무손실" in self.preset:
                args.extend(['-preset', 'p7', '-tune', 'lossless', '-rc', 'constqp', '-qp', '0', '-pix_fmt', 'yuv420p'])
            elif "최소 손실" in self.preset:
                args.extend(['-preset', 'p6', '-tune', 'hq', '-rc', 'vbr', '-cq', '19', '-b:v', '0', '-pix_fmt', 'yuv420p'])
            elif "최대 압축" in self.preset:
                args.extend(['-preset', 'p7', '-tune', 'hq', '-rc', 'vbr', '-cq', '30', '-b:v', '0', '-pix_fmt', 'yuv420p'])
            else:
                args.extend(['-preset', 'p4', '-tune', 'hq', '-rc', 'vbr', '-b:v', '5M', '-pix_fmt', 'yuv420p'])
            return args

        if "HEVC" in self.codec:
            args = ['-c:v', 'libx265']
            if "무손실" in self.preset:
                args.extend(['-x265-params', 'lossless=1'])
            elif "최소 손실" in self.preset:
                args.extend(['-crf', '20', '-preset', 'slow'])
            elif "최대 압축" in self.preset:
                args.extend(['-crf', '30', '-preset', 'veryslow'])
            else:
                args.extend(['-crf', '26', '-preset', 'medium'])
            return args

        if "VP9" in self.codec:
            args = ['-c:v', 'libvpx-vp9']
            if "무손실" in self.preset:
                args.extend(['-lossless', '1'])
            elif "최소 손실" in self.preset:
                args.extend(['-crf', '15', '-b:v', '0'])
            elif "최대 압축" in self.preset:
                args.extend(['-crf', '40', '-b:v', '0'])
            else:
                args.extend(['-crf', '30', '-b:v', '0'])
            return args

        return []

    @staticmethod
    def _is_progress_line(line):
        prefixes = (
            'frame=',
            'fps=',
            'stream_',
            'bitrate=',
            'total_size=',
            'out_time',
            'dup_frames=',
            'drop_frames=',
            'speed=',
            'progress=',
        )
        return line.startswith(prefixes)

    def perform_transcode(self, source_file, ffmpeg_path, encoding, startupinfo):
        self.log_message.emit(f"Starting Post-Process: {self.codec} (Threads: {self.threads})")
        self.status_update.emit("인코딩 중")
        self.progress_update.emit(0, "Encoding...", "Calculating...")

        base, source_ext = os.path.splitext(source_file)
        output_ext = f".{self.target_ext.lower()}" if self.target_ext else source_ext
        output_file = f"{base}{output_ext}"

        if output_ext.lower() == '.webm' and "VP9" not in self.codec:
            self.error_occurred.emit("WebM 컨테이너에서는 VP9 코덱만 지원됩니다.")
            return False

        if (
            not self.overwrite
            and os.path.normcase(output_file) != os.path.normcase(source_file)
            and os.path.exists(output_file)
        ):
            self.log_message.emit(f"Output file already exists, skipping encoding: {output_file}")
            self.progress_update.emit(100, "Done (Skipped)", "")
            return True

        temp_output = f"{base}_encoding{output_ext}"
        self._track_file(source_file)
        self._track_file(temp_output)
        self.current_filename = temp_output

        duration_sec, source_audio_codec = self._probe_media_info(source_file, ffmpeg_path, encoding, startupinfo)

        ffmpeg_cmd = [ffmpeg_path, '-y', '-progress', 'pipe:1', '-nostats']
        if self.threads > 0:
            ffmpeg_cmd.extend(['-threads', str(self.threads)])

        ffmpeg_cmd.extend(['-i', source_file])
        ffmpeg_cmd.extend(self._select_video_args())
        ffmpeg_cmd.extend(self._select_audio_args(output_ext, source_audio_codec))

        if output_ext.lower() == '.mp4':
            ffmpeg_cmd.extend(['-movflags', '+faststart'])

        ffmpeg_cmd.append(temp_output)

        self.logger.debug(f"Encoding command: {' '.join(ffmpeg_cmd)}")

        error_tail = collections.deque(maxlen=20)
        self.process = subprocess.Popen(
            ffmpeg_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding=encoding,
            errors='replace',
            startupinfo=startupinfo,
        )

        while self.is_running:
            line = self.process.stdout.readline()
            if not line:
                if self.process.poll() is not None:
                    break
                continue

            line = line.strip()
            if not line:
                continue

            self.logger.debug(f"[ffmpeg] {line}")
            if not self._is_progress_line(line):
                error_tail.append(line)

            if duration_sec <= 0:
                continue

            if line.startswith('out_time_ms=') or line.startswith('out_time_us='):
                try:
                    current_sec = int(line.split('=', 1)[1]) / 1_000_000
                    self.emit_encoding_progress(current_sec, duration_sec)
                except ValueError:
                    pass
            elif line.startswith('out_time='):
                current_sec = self.parse_timestamp_seconds(line.split('=', 1)[1])
                if current_sec is not None:
                    self.emit_encoding_progress(current_sec, duration_sec)
            elif "time=" in line:
                match = re.search(r'time=(\d+:\d{2}:\d{2}(?:\.\d+)?)', line)
                if match:
                    current_sec = self.parse_timestamp_seconds(match.group(1))
                    if current_sec is not None:
                        self.emit_encoding_progress(current_sec, duration_sec)

        if not self.is_running:
            terminate_process_tree(self.process, self.logger)
            if os.path.exists(temp_output):
                try:
                    retry_file_op(lambda: os.remove(temp_output))
                except OSError:
                    pass
            return False

        rc = self.process.wait()

        if rc == 0 and os.path.exists(temp_output) and os.path.getsize(temp_output) > 0:
            try:
                retry_file_op(lambda: os.replace(temp_output, output_file))
            except OSError as e:
                self.error_occurred.emit(f"Failed to finalize encoded file: {e}")
                return False

            if os.path.normcase(source_file) != os.path.normcase(output_file) and os.path.exists(source_file):
                try:
                    retry_file_op(lambda: os.remove(source_file))
                except OSError as e:
                    self.logger.debug(f"Could not remove intermediate source file {source_file}: {e}")

            self.current_filename = output_file
            self.log_message.emit("Encoding completed.")
            self.progress_update.emit(100, "Done", "")
            return True

        if os.path.exists(temp_output):
            try:
                retry_file_op(lambda: os.remove(temp_output))
            except OSError:
                pass

        for err_line in error_tail:
            self.log_message.emit(f"[ffmpeg] {err_line}")

        self.error_occurred.emit(f"Encoding failed: {rc}")
        return False

    def parse_progress(self, line):
        try:
            percent_match = re.search(r'\[download\]\s+(\d+(?:\.\d+)?)%', line)
            if not percent_match:
                return

            speed_match = re.search(r'\bat\s+([^\s]+/s)', line)
            eta_match = re.search(r'\bETA\s+([^\s]+)', line)
            percent = max(0, min(float(percent_match.group(1)), 100))
            speed_str = speed_match.group(1) if speed_match else "-"
            eta_str = eta_match.group(1) if eta_match else ""
            self.progress_update.emit(percent, speed_str, eta_str)
        except Exception:
            pass

    def cleanup_temp_files(self):
        targets = list(self.tracked_files)
        if self.current_filename:
            norm_curr = os.path.normpath(self.current_filename)
            if norm_curr not in targets:
                targets.append(norm_curr)

        patterns = []
        for target in targets:
            escaped_target = glob.escape(target)
            base = os.path.splitext(target)[0]
            escaped_base = glob.escape(base)
            patterns.extend([
                f"{escaped_target}.part",
                f"{escaped_target}.part-Frag*",
                f"{escaped_target}.ytdl",
                f"{escaped_base}.part",
                f"{escaped_base}.part-Frag*",
                f"{escaped_base}.ytdl",
                f"{escaped_base}.*.part",
                f"{escaped_base}.*.part-Frag*",
                f"{escaped_base}_raw*",
                f"{escaped_base}_encoding*",
            ])

        seen = set()
        for pattern in patterns:
            for path in glob.glob(pattern):
                norm = os.path.normcase(os.path.normpath(path))
                if norm in seen:
                    continue
                seen.add(norm)
                try:
                    retry_file_op(lambda p=path: os.remove(p), retries=5, delay=0.2)
                    self.logger.debug(f"Deleted cleanup: {path}")
                except OSError:
                    pass

    def stop(self):
        self.is_running = False
        self._cancelled = True
        self.log_message.emit("Stopping process...")
        terminate_process_tree(self.process, self.logger)


class DownloaderThread(QThread):
    def __init__(self, downloader):
        super().__init__()
        self.downloader = downloader

    def run(self):
        self.downloader.start_download()
