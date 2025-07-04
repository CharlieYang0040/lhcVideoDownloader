import logging
import os
import uuid  # 고유 ID 생성용
from enum import Enum, auto  # Enum 임포트 추가
from PySide6.QtCore import QObject, Signal, Slot
from app.config_manager import ConfigManager
from app.workers import ExtractWorker, DownloadWorker, BaseWorker  # 워커 클래스 임포트

log = logging.getLogger(__name__)


# --- Task Status Enum 정의 ---
class TaskStatus(Enum):
    """작업의 현재 상태를 나타내는 열거형."""
    PENDING_EXTRACT = auto()  # 추출 대기 (초기 상태)
    EXTRACTING = auto()  # 정보 추출 중
    PENDING_DOWNLOAD = auto()  # 다운로드 대기 (추출 완료 후)
    DOWNLOADING = auto()  # 다운로드 중
    PROCESSING = auto()  # 후처리 중 (FFmpeg 등)
    COMPLETED = auto()  # 완료
    FAILED = auto()  # 실패
    CANCELLING = auto()  # 취소 중
    CANCELLED = auto()  # 취소됨


# --- Task Status Enum 정의 끝 ---


class TaskManager(QObject):
    """추출 및 다운로드 작업을 관리하고 워커 스레드를 제어하는 클래스."""
    # 메인 앱으로 전달할 시그널 정의
    # log_updated = Signal(str)            # 제거
    task_progress = Signal(str, int, int)  # task_id, value, max
    task_finished = Signal(str, bool)  # task_id, success
    task_added = Signal(str, str)  # task_id, initial_status_text
    # task_status_changed = Signal(str, str) # task_id, status_text

    def __init__(self, ffmpeg_path):
        """TaskManager 초기화.

        Args:
            ffmpeg_path (str): FFmpeg 실행 파일 경로.
        """
        super().__init__()
        self.workers = {}  # 활성 워커 저장 (task_id: worker_instance)
        self.task_info = (
            {}
        )  # 작업 관련 정보 저장 (task_id: {url, save_path, cookie_file, status, output_file})
        self.ffmpeg_path = ffmpeg_path  # FFmpeg 경로 저장
        # ConfigManager 인스턴스 생성 (ydl 옵션 로드용)
        # 주의: ConfigManager가 다른 곳에서도 사용된다면 싱글톤 또는 의존성 주입 고려
        self.config_manager = ConfigManager()
        log.info(f"TaskManager initialized with ffmpeg path: {self.ffmpeg_path}")

    def _generate_task_id(self, title):
        """동영상 제목을 기반으로 안전한 파일명 형식의 기본 Task ID 생성."""
        safe_title = "".join(
            [
                c if c.isalnum() or c in (" ", "-", "_", ".", "[", "]") else "_"
                for c in title
            ]
        )
        # 너무 길지 않게 자르기 (선택 사항)
        safe_title = safe_title[:100]
        # 간단한 UUID 추가하여 고유성 보장 (더 안전)
        # task_id = f"{safe_title}_{uuid.uuid4().hex[:8]}"
        # 여기서는 일단 safe_title을 기본 ID로 사용하고, Worker 시작 시 최종 파일명으로 확정
        return safe_title

    def _get_unique_output_path(self, save_path, task_id_base):
        """지정된 저장 경로에 중복되지 않는 최종 출력 파일 경로 생성."""
        output_file = os.path.join(save_path, f"{task_id_base}.mp4")
        counter = 1
        base_name = os.path.splitext(output_file)[0]
        while os.path.exists(output_file):
            output_file = f"{base_name}_{counter}.mp4"
            counter += 1
        return output_file

    def _update_task_status(self, task_id, status: TaskStatus, status_text: str = ""):
        """작업 상태 업데이트 및 로그 기록.

        Args:
            task_id (str): 상태를 업데이트할 작업의 ID.
            status (TaskStatus): 새로운 작업 상태.
            status_text (str, optional): 상태 변경 시 UI에 표시될 텍스트. Defaults to "".

        Returns:
            bool: 상태 업데이트 성공 여부.
        """
        if task_id in self.task_info:
            old_status = self.task_info[task_id].get("status")
            if old_status != status:
                self.task_info[task_id]["status"] = status
                log.info(
                    f"[{task_id}] Status changed: {old_status.name if old_status else 'None'} -> {status.name}"
                )
                # 상태 변경 시그널 발생 (필요 시)
                # display_text = status_text or f"{task_id} - {status.name}"
                # self.task_status_changed.emit(task_id, status, display_text)
            return True
        else:
            log.warning(f"Attempted to update status for non-existent task: {task_id}")
            return False

    def add_download_task(
        self, url: str, output_path: str, cookie_file: str | None, start_time: str | None, end_time: str | None, debug_mode: bool = False
    ):
        """새로운 추출 및 다운로드 작업을 시작합니다.

        임시 ID로 ExtractWorker를 시작하고, 추출 성공 시
        최종 ID(파일명 기반)로 DownloadWorker를 시작합니다.

        Args:
            url (str): 다운로드할 YouTube 비디오 URL.
            output_path (str): 파일을 저장할 디렉토리 경로.
            cookie_file (str | None): 사용할 쿠키 파일 경로 (로그인 필요 시).
            start_time (str | None): 다운로드 시작 시간 (예: "HH:MM:SS").
            end_time (str | None): 다운로드 종료 시간 (예: "HH:MM:SS").
            debug_mode (bool): 디버그 로그 활성화 여부.
        """
        temp_task_id = f"Extracting_{uuid.uuid4().hex[:8]}"
        log.info(f"[{temp_task_id}] New task received for URL: {url}")

        self.task_info[temp_task_id] = {
            "url": url,
            "save_path": output_path,
            "cookie_file": cookie_file,
            "status": TaskStatus.EXTRACTING,
            "output_file": None,
            "start_time": start_time,
            "end_time": end_time,
            "debug_mode": debug_mode, # 디버그 모드 저장
        }

        # UI에 작업 추가 알림
        initial_status_text = f"{temp_task_id} - Preparing..."
        self.task_added.emit(temp_task_id, initial_status_text)
        self._update_task_status(
            temp_task_id, TaskStatus.EXTRACTING, f"{temp_task_id} - Extracting info..."
        )

        # 추출용 기본 옵션 로드 (필요 시 별도 옵션 사용 가능)
        base_extract_opts = self.config_manager.get_ydl_options()
        # 추출 시에는 download=False 이므로 관련 옵션 제거/수정
        base_extract_opts.pop("progress_hooks", None)
        base_extract_opts.pop("outtmpl", None)
        base_extract_opts.pop("writethumbnail", None)
        base_extract_opts.pop("postprocessors", None)
        base_extract_opts.pop("postprocessor_args", None)
        base_extract_opts["quiet"] = True  # 추출 시에는 더 조용히
        base_extract_opts["no_warnings"] = True

        extractor = ExtractWorker(temp_task_id, url, cookie_file, base_extract_opts)
        extractor.signals.result.connect(self._handle_extract_result)
        extractor.signals.finished.connect(self._handle_worker_finished)
        self.workers[temp_task_id] = extractor
        extractor.start()
        log.info(f"[{temp_task_id}] ExtractWorker started.")

    @Slot(str, dict)
    def _handle_extract_result(self, task_id, result):
        """ExtractWorker의 결과 처리. 성공 시 DownloadWorker 시작.

        Args:
            task_id (str): 결과를 반환한 임시 ExtractWorker의 ID.
            result (dict): 추출 결과 (title, formats, error 포함).
        """
        temp_task_id = task_id
        log.info(f"[{temp_task_id}] Handling extract result...")

        # 작업 유효성 검사
        if temp_task_id not in self.task_info or temp_task_id not in self.workers:
            log.warning(
                f"Received extract result for unknown or already finished task: {temp_task_id}"
            )
            return
        if self.task_info[temp_task_id].get("status") != TaskStatus.EXTRACTING:
            log.warning(
                f"Received extract result for task {temp_task_id} not in EXTRACTING state."
            )
            return

        task_data = self.task_info[temp_task_id]

        if result["error"]:
            log.error(f"[{temp_task_id}] Extraction failed: {result['error']}")
            self._update_task_status(temp_task_id, TaskStatus.FAILED)
            # 실패 시 작업 완료 처리는 _handle_worker_finished 에서 함
        else:
            log.info(
                f"[{temp_task_id}] Extraction successful. Title: {result['title']}"
            )

            # 최종 Task ID 및 출력 경로 결정
            final_task_id_base = self._generate_task_id(result["title"])
            output_file = self._get_unique_output_path(
                task_data["save_path"], final_task_id_base
            )
            final_task_id = os.path.basename(output_file)  # 파일명을 최종 ID로 사용
            log.info(
                f"[{temp_task_id} -> {final_task_id}] Determined final task ID and output file: {output_file}"
            )

            # Task 정보 업데이트: 새 ID로 정보 복사 및 상태 변경
            task_data["output_file"] = output_file
            task_data["status"] = TaskStatus.PENDING_DOWNLOAD  # 다운로드 대기 상태
            self.task_info[final_task_id] = task_data

            # 임시 ID 정보 제거
            del self.task_info[temp_task_id]
            # 임시 워커 참조 제거 (workers 딕셔너리에서는 finished 핸들러에서 제거)
            log.debug(
                f"[{temp_task_id}] Temporary task info removed, transitioning to {final_task_id}."
            )

            # UI 업데이트: 임시 ID 완료 알림(UI에서 제거) 후 최종 ID로 추가
            self.task_finished.emit(temp_task_id, True)
            download_status_text = f"{final_task_id} - Starting download..."
            self.task_added.emit(final_task_id, download_status_text)
            self._update_task_status(
                final_task_id, TaskStatus.DOWNLOADING, download_status_text
            )

            # 다운로드용 기본 옵션 로드
            base_download_opts = self.config_manager.get_ydl_options()

            # DownloadWorker 생성 및 시작
            downloader = DownloadWorker(
                final_task_id,
                task_data["url"],
                output_file,
                self.ffmpeg_path,
                task_data["cookie_file"],
                base_download_opts,  # 기본 옵션 전달
                start_time=task_data["start_time"], # 시작 시간 전달
                end_time=task_data["end_time"],     # 종료 시간 전달
                debug_mode=task_data["debug_mode"], # 디버그 모드 전달
            )
            downloader.signals.progress.connect(self._handle_progress)
            downloader.signals.finished.connect(self._handle_worker_finished)
            self.workers[final_task_id] = downloader  # 새 ID로 워커 등록
            downloader.start()
            log.info(f"[{final_task_id}] DownloadWorker started.")

    @Slot(str, int, int)
    def _handle_progress(self, task_id, value, max_value):
        """워커로부터 진행률 업데이트를 받아 메인 앱으로 전달."""
        if task_id in self.task_info:
            # 다운로드 중 상태 업데이트 (필요 시 후처리 상태도 반영)
            current_status = self.task_info[task_id].get("status")
            if (
                current_status == TaskStatus.DOWNLOADING
                or current_status == TaskStatus.PROCESSING
            ):
                if max_value == 0 and value == 0:  # 불확정 진행률 (예: 후처리 시작)
                    self._update_task_status(task_id, TaskStatus.PROCESSING)
                self.task_progress.emit(task_id, value, max_value)
        else:
            log.debug(f"Received progress for unknown or finished task: {task_id}")

    @Slot(str, bool)
    def _handle_worker_finished(self, task_id, success):
        """워커 스레드 종료 시 호출되어 작업 상태를 업데이트하고 정리."""
        log.info(f"[{task_id}] Worker finished signal received. Success: {success}")

        if task_id not in self.workers:
            # 이미 처리되었거나 알 수 없는 워커 (예: 성공한 임시 ExtractWorker)
            log.debug(
                f"Received finish signal for already removed or unknown worker: {task_id}"
            )
            return

        # 워커 인스턴스 제거
        del self.workers[task_id]

        if task_id not in self.task_info:
            # task_info가 없는 경우 (예: 추출 성공 후 ID 변경된 임시 ID)
            log.info(
                f"Worker finished for task {task_id} which info was already transitioned or removed."
            )
            return

        current_status = self.task_info[task_id].get("status")
        log.debug(
            f"Handling finish signal for task {task_id} with status: {current_status.name if current_status else 'None'}"
        )

        final_status = TaskStatus.FAILED  # 기본값을 FAILED로 변경
        emit_success = False  # task_finished 시그널에 전달할 값

        if current_status == TaskStatus.EXTRACTING:
            if success:
                # 성공 시 _handle_extract_result 에서 처리했으므로 여기서는 별도 처리 없음
                # (워커 참조는 이미 위에서 제거됨)
                return  # 여기서 함수 종료
            else:
                log.error(f"[{task_id}] Extraction failed or was cancelled.")
                final_status = (
                    TaskStatus.FAILED
                    if not self.task_info[task_id].get("status")
                    == TaskStatus.CANCELLING
                    else TaskStatus.CANCELLED
                )
                emit_success = False
        elif current_status in [
            TaskStatus.DOWNLOADING,
            TaskStatus.PROCESSING,
            TaskStatus.PENDING_DOWNLOAD,
        ]:  # 다운로드 관련 상태
            if success:
                log.info(f"[{task_id}] Download and processing completed successfully.")
                final_status = TaskStatus.COMPLETED
                emit_success = True
                # --- 수정 시간 업데이트 로직 --- (성공 시)
                output_file = self.task_info[task_id].get("output_file")
                log.debug(f"[{task_id}] Checking for file to update mtime. Path: {output_file}")
                if output_file and os.path.exists(output_file):
                    try:
                        # 현재 시간으로 파일 수정 시간을 업데이트
                        os.utime(output_file, None)
                        log.info(
                            f"[{task_id}] Successfully updated modification time for {output_file}"
                        )
                    except Exception as e:
                        log.error(
                            f"[{task_id}] Failed to update modification time for {output_file}: {e}"
                        )
                else:
                    log.warning(f"[{task_id}] Could not update mtime. File not found at path: {output_file}")
                # --- 수정 시간 업데이트 로직 끝 ---
            else:
                # 실패 또는 취소
                is_cancelling = (
                    self.task_info[task_id].get("status") == TaskStatus.CANCELLING
                )
                log.warning(f"[{task_id}] Download/processing failed or was cancelled.")
                final_status = (
                    TaskStatus.CANCELLED if is_cancelling else TaskStatus.FAILED
                )
                emit_success = False
        elif current_status == TaskStatus.CANCELLING:
            log.info(f"[{task_id}] Worker finished after cancellation request.")
            final_status = TaskStatus.CANCELLED
            emit_success = False
        else:
            log.warning(
                f"[{task_id}] Worker finished in unexpected state: {current_status.name if current_status else 'None'}. Marking as Failed."
            )
            final_status = TaskStatus.FAILED
            emit_success = False

        # 최종 상태 업데이트
        self._update_task_status(task_id, final_status)
        # 완료/실패 시그널 발생
        self.task_finished.emit(task_id, emit_success)
        # 작업 정보 정리 (선택적: 완료/실패 후에도 정보 유지 가능)
        self._cleanup_task_info(task_id)  # 워커는 이미 제거됨

    def _cleanup_task_info(self, task_id):
        """완료, 실패 또는 취소된 작업의 정보를 self.task_info에서 제거."""
        if task_id in self.task_info:
            log.debug(f"Cleaning up task info for: {task_id}")
            del self.task_info[task_id]

    @Slot(str)
    def cancel_task(self, task_id):
        """특정 작업을 취소 요청.

        현재 진행 중인 워커에 취소 신호를 보내고 상태를 CANCELLING으로 변경합니다.
        워커가 없거나 이미 종료된 상태면 즉시 CANCELLED로 처리합니다.

        Args:
            task_id (str): 취소할 작업의 ID.
        """
        log.info(f"Request received to cancel task: {task_id}")

        if task_id in self.task_info:
            current_status = self.task_info[task_id].get("status")
            # 이미 완료/실패/취소된 작업은 취소 불가
            if current_status in [
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
                TaskStatus.CANCELLING,
            ]:
                log.warning(
                    f"Cannot cancel task {task_id}, it is already in state: {current_status.name}"
                )
                return

            # 상태를 CANCELLING으로 변경
            self._update_task_status(
                task_id, TaskStatus.CANCELLING, f"{task_id} - Cancelling..."
            )

            # 활성 워커에 취소 요청
            if task_id in self.workers:
                worker = self.workers[task_id]
                log.info(
                    f"[{task_id}] Calling cancel() on worker {worker.__class__.__name__}"
                )
                worker.cancel()
            else:
                # 워커가 아직 시작되지 않았거나 이미 종료된 경우 (예: PENDING 상태)
                log.warning(
                    f"[{task_id}] No active worker found to cancel, marking as Cancelled."
                )
                # 즉시 CANCELLED 상태로 변경하고 완료 처리
                self._update_task_status(task_id, TaskStatus.CANCELLED)
                self.task_finished.emit(task_id, False)
                self._cleanup_task_info(task_id)
        else:
            log.warning(f"Attempted to cancel non-existent task: {task_id}")

    def get_active_tasks(self):
        """현재 관리 중인 (완료/실패/취소되지 않은) 작업 ID 목록 반환."""
        # 필요 시 상태별 필터링 추가
        return list(self.task_info.keys())

    def stop_all_tasks(self):
        """앱 종료 시 모든 활성 작업을 취소 요청."""
        log.info("Stopping all active tasks...")
        # task_info 기준으로 취소 요청 (workers 딕셔너리는 변경될 수 있음)
        task_ids_to_cancel = list(self.task_info.keys())
        for task_id in task_ids_to_cancel:
            self.cancel_task(task_id)
        # 모든 스레드가 종료될 때까지 기다리는 로직 추가 가능 (앱 종료 지연 발생)
        # log.info("Waiting for workers to finish...")
        # for worker in list(self.workers.values()):
        #     worker.wait()
        # log.info("All workers finished.")
