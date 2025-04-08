import logging
import os
from PySide6.QtCore import Signal, QThread, QMutex, QWaitCondition, QObject
import yt_dlp
import time

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
        self, task_id, url, output_file, ffmpeg_path, cookie_file=None, base_opts=None, parent=None
    ):
        """DownloadWorker 초기화.

        Args:
            task_id (str): 작업 ID.
            url (str): 다운로드할 비디오 URL.
            output_file (str): 저장될 최종 파일 경로.
            ffmpeg_path (str): FFmpeg 실행 파일 경로.
            cookie_file (str | None, optional): 사용할 쿠키 파일 경로.
            base_opts (dict | None, optional): yt-dlp 기본 옵션.
            parent (QObject, optional): 부모 객체. Defaults to None.
        """
        super().__init__(task_id, parent)
        self.url = url
        self.output_file = output_file
        self.ffmpeg_path = ffmpeg_path
        self.cookie_file = cookie_file
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
            self.signals.progress.emit(self.task_id, 100, 100)
        elif status == "error":
            log.error(f"[{self.task_id}] Download hook reported an error.")

    def run(self):
        """yt-dlp를 사용하여 비디오 다운로드 및 후처리 실행."""
        log.info(f"[{self.task_id}] Starting download for URL: {self.url}")
        self.ydl = None
        try:
            if not self.ffmpeg_path:
                # ffmpeg_path는 TaskManager에서 이미 확인했어야 함
                log.error(f"[{self.task_id}] FFmpeg path is not set.")
                self.signals.finished.emit(self.task_id, False)
                return

            log.info(f"[{self.task_id}] Using FFmpeg from: {self.ffmpeg_path}")
            log.info(f"[{self.task_id}] Output file: {self.output_file}")
            log.info(
                f"[{self.task_id}] Starting download, conversion, and thumbnail embedding..."
            )

            # 기본 옵션 복사 후 작업별 옵션 추가/수정
            ydl_opts = self.base_opts.copy()

            # 작업별 필수 옵션 설정
            ydl_opts["outtmpl"] = self.output_file
            ydl_opts["progress_hooks"] = [self.progress_hook]
            ydl_opts["ffmpeg_location"] = self.ffmpeg_path

            if self.cookie_file:
                ydl_opts["cookiefile"] = self.cookie_file
                log.info(f"[{self.task_id}] Using cookie file: {self.cookie_file}")

            # download=True 는 기본값이거나 명시적으로 설정 (base_opts 에 있을 수 있음)
            # ydl_opts['download'] = True

            # yt-dlp 인스턴스 생성
            self.ydl = yt_dlp.YoutubeDL(ydl_opts)

            if self.is_cancelled():
                log.info(
                    f"[{self.task_id}] Download cancelled before starting download."
                )
                self.signals.finished.emit(self.task_id, False)
                return

            self.ydl.download([self.url])

            if self.is_cancelled():
                log.info(
                    f"[{self.task_id}] Download likely cancelled during operation (checked after ydl.download call)."
                )
                self.signals.finished.emit(self.task_id, False)
                return

            log.info(f"[{self.task_id}] Download process finished successfully!")
            self.signals.finished.emit(self.task_id, True)

        except yt_dlp.utils.DownloadCancelled as cancel_err:
            log.warning(f"[{self.task_id}] Download explicitly cancelled: {cancel_err}")
            self.signals.finished.emit(self.task_id, False)
        except yt_dlp.utils.YoutubeDLError as ydl_err:
            if self.is_cancelled():
                log.warning(
                    f"[{self.task_id}] Download likely cancelled, yt-dlp error occurred: {ydl_err}"
                )
                self.signals.finished.emit(self.task_id, False)
            else:
                log.error(
                    f"[{self.task_id}] Download failed due to yt-dlp error: {ydl_err}"
                )
                self.signals.finished.emit(self.task_id, False)
        except Exception as e:
            if self.is_cancelled():
                log.warning(
                    f"[{self.task_id}] Download likely cancelled, general exception occurred: {e}"
                )
                self.signals.finished.emit(self.task_id, False)
            else:
                log.exception(
                    f"[{self.task_id}] An unexpected error occurred during download"
                )
                self.signals.finished.emit(self.task_id, False)
        finally:
            self.ydl = None
            log.debug(f"[{self.task_id}] Download worker finished execution.")
