import logging
import os
from PySide6.QtCore import Signal, QThread, QMutex, QWaitCondition, QObject
import yt_dlp
import time
import subprocess

# 모듈 레벨 로거 설정
log = logging.getLogger(__name__)


class WorkerSignals(QObject):
    """워커 스레드에서 메인 스레드로 보내는 시그널 정의."""
    progress = Signal(str, int, int)  # task_id, value, max
    result = Signal(str, dict)  # task_id, result_dict (ExtractWorker)
    finished = Signal(str, bool)  # task_id, success
    error = Signal(str, str)  # task_id, error_message (오류 발생 시 사용)


class BaseWorker(QThread):
    """모든 워커 스레드의 기반 클래스. 공통 기능(취소 등) 제공."""
    def __init__(self, task_id, parent=None):
        """BaseWorker 초기화.

        Args:
            task_id (str): 워커가 처리할 작업의 ID.
            parent (QObject, optional): 부모 객체. Defaults to None.
        """
        super().__init__(parent)
        self.task_id = task_id
        self.signals = WorkerSignals()
        self._is_cancelled = False
        self._mutex = QMutex()
        # _condition은 현재 사용되지 않으므로 유지 또는 제거 고려 (일단 유지)
        self._condition = QWaitCondition()

    def cancel(self):
        """작업 취소를 요청합니다 (취소 플래그 설정)."""
        log.info(f"[{self.task_id}] Cancellation requested for worker.")
        self._mutex.lock()
        try:
            self._is_cancelled = True
        finally:
            self._mutex.unlock()
        # yt-dlp와 같은 외부 프로세스 중단 로직은 각 워커 run 메서드의 예외 처리에서 관리

    def is_cancelled(self):
        """취소 상태 확인"""
        self._mutex.lock()
        try:
            cancelled = self._is_cancelled
        finally:
            self._mutex.unlock()
        return cancelled

    def run(self):
        """워커의 메인 실행 로직 (서브클래스에서 구현 필요)."""
        raise NotImplementedError("Subclasses must implement the run method.")


class ExtractWorker(BaseWorker):
    """YouTube URL에서 비디오 정보를 추출하는 워커."""
    # 생성자에 base_opts 추가
    def __init__(self, task_id, url, cookie_file=None, base_opts=None, parent=None):
        """ExtractWorker 초기화.

        Args:
            task_id (str): 작업 ID.
            url (str): 정보를 추출할 YouTube URL.
            cookie_file (str | None, optional): 사용할 쿠키 파일 경로.
            base_opts (dict | None, optional): yt-dlp 기본 옵션.
            parent (QObject, optional): 부모 객체. Defaults to None.
        """
        super().__init__(task_id, parent)
        self.url = url
        self.cookie_file = cookie_file
        # 기본 옵션 저장 (없으면 빈 dict)
        self.base_opts = base_opts if base_opts is not None else {}

    def run(self):
        """yt-dlp를 사용하여 비디오 정보 추출 실행."""
        log.info(f"[{self.task_id}] Starting extraction for URL: {self.url}")
        try:
            log.info(
                f"[{self.task_id}] Attempting to connect to YouTube URL: {self.url}"
            )

            # 기본 옵션 복사 후 작업별 옵션 추가
            ydl_opts = self.base_opts.copy()

            if self.cookie_file:
                ydl_opts["cookiefile"] = self.cookie_file
                log.info(f"[{self.task_id}] Using cookie file: {self.cookie_file}")

            # download=False 는 추출의 핵심이므로 여기서 설정
            ydl_opts["download"] = False

            # 취소 확인
            if self.is_cancelled():
                log.info(
                    f"[{self.task_id}] Extraction cancelled before starting yt-dlp."
                )
                self.signals.finished.emit(self.task_id, False)
                return

            # yt-dlp 인스턴스 생성
            ydl = yt_dlp.YoutubeDL(ydl_opts)

            log.info(f"[{self.task_id}] Retrieving video information...")
            info = ydl.extract_info(
                self.url, download=False
            )  # download=False 중복이지만 명확성 위해 유지

            # 추출 후 취소 확인
            if self.is_cancelled():
                log.info(
                    f"[{self.task_id}] Extraction cancelled after retrieving info."
                )
                self.signals.finished.emit(self.task_id, False)
                return

            if not info:
                error_msg = "Failed to retrieve video information"
                log.error(f"[{self.task_id}] {error_msg}")
                self.signals.result.emit(
                    self.task_id,
                    {"title": "Unknown", "formats": [], "error": error_msg},
                )
                self.signals.finished.emit(self.task_id, False)
                return

            title = info.get("title", f"video_{info.get('id', 'unknown')}")
            log.info(f"[{self.task_id}] Found title: {title}")

            seen_resolutions = set()
            formats = []
            for f in info.get("formats", []):
                if f.get("height") and f.get("vcodec") != "none":
                    resolution = f'{f.get("height")}p'
                    if resolution not in seen_resolutions:
                        seen_resolutions.add(resolution)
                        formats.append(
                            {
                                "resolution": resolution,
                                "format_id": f["format_id"],
                                "ext": f.get("ext", ""),
                                "vcodec": f.get("vcodec", ""),
                                "acodec": f.get("acodec", ""),
                            }
                        )
                        log.debug(
                            f"[{self.task_id}] Found format: {resolution} ({f.get('ext', 'unknown')})"
                        )

            if not formats:
                error_msg = "No compatible video formats found"
                log.warning(f"[{self.task_id}] {error_msg}")
                self.signals.result.emit(
                    self.task_id, {"title": title, "formats": [], "error": error_msg}
                )
                self.signals.finished.emit(self.task_id, False)
                return

            formats.sort(
                key=lambda x: int(x["resolution"].replace("p", "")), reverse=True
            )

            log.info(f"[{self.task_id}] Extraction successful.")
            self.signals.result.emit(
                self.task_id, {"title": title, "formats": formats, "error": None}
            )
            self.signals.finished.emit(self.task_id, True)

        except Exception as e:
            if self.is_cancelled():
                log.warning(
                    f"[{self.task_id}] Extraction cancelled during operation (exception occurred: {e})"
                )
                self.signals.result.emit(
                    self.task_id,
                    {
                        "title": "Unknown",
                        "formats": [],
                        "error": "Extraction cancelled",
                    },
                )
                self.signals.finished.emit(self.task_id, False)
            else:
                log.exception(f"[{self.task_id}] Error during extraction")
                self.signals.result.emit(
                    self.task_id,
                    {"title": "Unknown", "formats": [], "error": f"Error: {str(e)}"},
                )
                self.signals.finished.emit(self.task_id, False)


class DownloadWorker(BaseWorker):
    """비디오를 다운로드하고 후처리하는 워커."""
    # 생성자에 base_opts 추가
    def __init__(
        self,
        task_id,
        url,
        output_file,
        ffmpeg_path,
        cookie_file=None,
        base_opts=None,
        start_time=None,
        end_time=None,
        debug_mode=False,
        parent=None,
    ):
        """DownloadWorker 초기화.

        Args:
            task_id (str): 작업 ID.
            url (str): 다운로드할 비디오 URL.
            output_file (str): 저장될 최종 파일 경로.
            ffmpeg_path (str): FFmpeg 실행 파일 경로.
            cookie_file (str | None, optional): 사용할 쿠키 파일 경로.
            base_opts (dict | None, optional): yt-dlp 기본 옵션.
            start_time (str | None, optional): 다운로드 시작 시간.
            end_time (str | None, optional): 다운로드 종료 시간.
            debug_mode (bool, optional): 디버그 로그 활성화 여부.
            parent (QObject, optional): 부모 객체. Defaults to None.
        """
        super().__init__(task_id, parent)
        self.url = url
        self.output_file = output_file
        self.ffmpeg_path = ffmpeg_path
        self.cookie_file = cookie_file
        self.start_time = start_time
        self.end_time = end_time
        self.debug_mode = debug_mode
        # 기본 옵션 저장 (없으면 빈 dict)
        self.base_opts = base_opts if base_opts is not None else {}
        self.ydl = None

    def progress_hook(self, d):
        """yt-dlp 진행률 콜백 함수. 진행률 시그널 전송 및 취소 확인."""
        if self.is_cancelled():
            log.info(f"[{self.task_id}] Cancellation detected in progress hook.")
            raise yt_dlp.utils.DownloadCancelled("Download cancelled by user.")

        status = d.get("status")
        if status == "downloading":
            downloaded = d.get("downloaded_bytes", 0)
            total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
            if total > 0:
                progress = int((downloaded / total) * 100)
                self.signals.progress.emit(self.task_id, progress, 100)
        elif status == "processing":
            log.debug(f"[{self.task_id}] Post-processing started...")
            self.signals.progress.emit(self.task_id, 0, 0)
        elif status == "finished":
            log.info(
                f"[{self.task_id}] Download/processing finished according to hook."
            )
            # 수동 FFmpeg 처리가 있으므로 여기서 100%를 보내지 않음
            # self.signals.progress.emit(self.task_id, 100, 100)
        elif status == "error":
            log.error(f"[{self.task_id}] Download hook reported an error.")

    def run(self):
        """
        비디오 다운로드 및 수동 후처리를 실행합니다.
        1. yt-dlp를 사용하여 비디오를 임시 mkv 파일로 다운로드합니다.
        2. subprocess를 사용하여 ffmpeg를 직접 실행하여 자르기, 변환을 수행합니다.
        """
        log.info(f"[{self.task_id}] Starting download for URL: {self.url}")
        self.ydl = None
        
        output_dir, output_filename = os.path.split(self.output_file)
        output_basename, _ = os.path.splitext(output_filename)
        temp_output_template = os.path.join(output_dir, f"{output_basename}.temp")
        temp_mkv_path = f"{temp_output_template}.mkv"
        
        try:
            # --- 1단계: yt-dlp로 임시 파일 다운로드 ---
            if not self.ffmpeg_path:
                log.error(f"[{self.task_id}] FFmpeg path is not set.")
                self.signals.finished.emit(self.task_id, False)
                return

            log.info(f"[{self.task_id}] Using FFmpeg from: {self.ffmpeg_path}")
            log.info(f"[{self.task_id}] Final output file: {self.output_file}")
            log.info(f"[{self.task_id}] Starting download to temporary file...")

            ydl_opts = self.base_opts.copy()
            ydl_opts["progress_hooks"] = [self.progress_hook]
            
            # yt-dlp가 내부적으로 다른 후처리(mp4 변환 등)를 하지 않도록 설정합니다.
            # 'postprocessors' 키를 완전히 삭제하여 yt-dlp가 포맷에 맞춰
            # 병합(merge)만 수행하도록 유도합니다.
            if "postprocessors" in ydl_opts:
                del ydl_opts["postprocessors"]

            ydl_opts["merge_output_format"] = "mkv"
            ydl_opts["outtmpl"] = temp_output_template

            if self.ffmpeg_path:
                # ffmpeg_location은 파일이 아닌 디렉토리로 지정해야 ffprobe 등 다른 도구도 찾을 수 있습니다.
                ffmpeg_dir = os.path.dirname(self.ffmpeg_path)
                ydl_opts["ffmpeg_location"] = ffmpeg_dir
                
            if self.cookie_file:
                ydl_opts["cookiefile"] = self.cookie_file

            if self.debug_mode:
                log.info(f"[{self.task_id}] Debug mode enabled for yt-dlp.")
                ydl_opts["verbose"] = True
                ydl_opts["logger"] = logging.getLogger(f"yt-dlp.{self.task_id}")

            self.ydl = yt_dlp.YoutubeDL(ydl_opts)

            if self.is_cancelled():
                log.info(f"[{self.task_id}] Download cancelled before starting.")
                self.signals.finished.emit(self.task_id, False)
                return

            self.ydl.download([self.url])

            if self.is_cancelled():
                raise yt_dlp.utils.DownloadCancelled("Download cancelled by user.")

            if not os.path.exists(temp_mkv_path):
                log.error(f"[{self.task_id}] Temporary MKV file not found: {temp_mkv_path}")
                self.signals.finished.emit(self.task_id, False)
                return
            
            log.info(f"[{self.task_id}] Temporary file downloaded: {temp_mkv_path}")
            
            # --- 썸네일 파일 처리 (이름 변경 및 .webp -> .png 변환) ---
            final_basename, _ = os.path.splitext(self.output_file)
            
            # 1. 임시 썸네일 파일 찾기
            temp_thumbnail_path = None
            original_ext = None
            for ext in ['webp', 'jpg', 'png']:
                path = f"{temp_output_template}.{ext}"
                if os.path.exists(path):
                    temp_thumbnail_path = path
                    original_ext = ext
                    log.info(f"[{self.task_id}] Found temporary thumbnail: {temp_thumbnail_path}")
                    break
            
            if temp_thumbnail_path:
                # 2. webp 포맷인 경우 png로 변환
                if original_ext == 'webp':
                    final_thumbnail_path = f"{final_basename}.png"
                    log.info(f"[{self.task_id}] Converting thumbnail from WEBP to PNG: {final_thumbnail_path}")
                    
                    ffmpeg_conv_cmd = [self.ffmpeg_path, "-y", "-i", temp_thumbnail_path, final_thumbnail_path]

                    try:
                        # subprocess.communicate()를 사용하여 데드락을 방지합니다.
                        process = subprocess.Popen(
                            ffmpeg_conv_cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            universal_newlines=True,
                            encoding='utf-8',
                            errors='replace',
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                        )
                        stdout, _ = process.communicate()

                        if self.debug_mode and stdout:
                            for line in stdout.splitlines():
                                log.debug(f"[ffmpeg-thumb-{self.task_id}] {line.strip()}")

                        if process.returncode == 0:
                            log.info(f"[{self.task_id}] Successfully converted thumbnail to PNG.")
                            os.remove(temp_thumbnail_path) # 성공 시 원본 임시 파일 삭제
                        else:
                            log.error(f"[{self.task_id}] FFmpeg thumbnail conversion failed with code {process.returncode}.")
                            if stdout:
                                log.error(f"[{self.task_id}] FFmpeg thumb output: {stdout}")
                            # 변환 실패 시 원본 이름으로 되돌림
                            fallback_path = f"{final_basename}.{original_ext}"
                            if os.path.exists(fallback_path): os.remove(fallback_path)
                            os.rename(temp_thumbnail_path, fallback_path)

                    except Exception as e:
                        log.error(f"[{self.task_id}] Error during thumbnail conversion: {e}. Falling back to renaming.")
                        fallback_path = f"{final_basename}.{original_ext}"
                        if os.path.exists(fallback_path): os.remove(fallback_path)
                        os.rename(temp_thumbnail_path, fallback_path)

                else: # .jpg, .png 등 다른 포맷은 이름만 변경
                    final_thumbnail_path = f"{final_basename}.{original_ext}"
                    try:
                        if os.path.exists(final_thumbnail_path):
                            os.remove(final_thumbnail_path)
                        os.rename(temp_thumbnail_path, final_thumbnail_path)
                        log.info(f"[{self.task_id}] Renamed thumbnail to: {final_thumbnail_path}")
                    except OSError as e:
                        log.warning(f"[{self.task_id}] Failed to rename thumbnail: {e}")

            # --- 2단계: FFmpeg 수동 실행 (자르기 및 변환) ---
            log.info(f"[{self.task_id}] Starting manual FFmpeg processing.")
            self.signals.progress.emit(self.task_id, 0, 0) # 처리 중 상태로 변경

            ffmpeg_cmd = [self.ffmpeg_path, "-y", "-i", temp_mkv_path]

            if self.start_time:
                ffmpeg_cmd.extend(["-ss", self.start_time])
            if self.end_time:
                ffmpeg_cmd.extend(["-to", self.end_time])

            # 설정에서 고품질 인코딩 옵션 가져오기
            pp_args = self.base_opts.get("postprocessor_args", {})
            convertor_args = pp_args.get("FFmpegVideoConvertor", [])
            if convertor_args:
                ffmpeg_cmd.extend(convertor_args)
            else:
                # 기본값 설정
                ffmpeg_cmd.extend(['-c:v', 'libx264', '-c:a', 'aac', '-pix_fmt', 'yuv420p'])
            
            if self.debug_mode:
                log.info(f"[{self.task_id}] Debug mode enabled for FFmpeg.")
                ffmpeg_cmd.extend(["-loglevel", "debug"])

            ffmpeg_cmd.append(self.output_file)

            log.info(f"[{self.task_id}] Executing FFmpeg command: {' '.join(ffmpeg_cmd)}")

            # subprocess.communicate()를 사용하여 데드락을 방지합니다.
            process = subprocess.Popen(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                encoding='utf-8',
                errors='replace',
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            stdout, _ = process.communicate()

            if self.debug_mode and stdout:
                for line in stdout.splitlines():
                    log.info(f"[ffmpeg-{self.task_id}] {line.strip()}")
            
            if self.is_cancelled():
                 raise yt_dlp.utils.DownloadCancelled("Download cancelled by user.")

            if process.returncode != 0:
                log.error(f"[{self.task_id}] FFmpeg processing failed with code {process.returncode}.")
                if stdout:
                    log.error(f"[{self.task_id}] FFmpeg output:\n{stdout}")
                self.signals.finished.emit(self.task_id, False)
                return
            
            log.info(f"[{self.task_id}] FFmpeg processing successful.")
            self.signals.progress.emit(self.task_id, 100, 100)
            self.signals.finished.emit(self.task_id, True)

        except yt_dlp.utils.DownloadCancelled as cancel_err:
            log.warning(f"[{self.task_id}] Download explicitly cancelled: {cancel_err}")
            self.signals.finished.emit(self.task_id, False)
        except Exception as e:
            if self.is_cancelled():
                log.warning(
                    f"[{self.task_id}] Download cancelled, general exception occurred: {e}"
                )
            else:
                log.exception(
                    f"[{self.task_id}] An unexpected error occurred during download"
                )
            self.signals.finished.emit(self.task_id, False)
        finally:
            # --- 3단계: 임시 파일 정리 ---
            if os.path.exists(temp_mkv_path):
                try:
                    os.remove(temp_mkv_path)
                    log.info(f"[{self.task_id}] Removed temporary file: {temp_mkv_path}")
                except OSError as e:
                    log.warning(f"[{self.task_id}] Failed to remove temp file {temp_mkv_path}: {e}")
            
            self.ydl = None
            log.debug(f"[{self.task_id}] Download worker finished execution.")
