import logging
import os
import uuid # 고유 ID 생성용
from PySide6.QtCore import QObject, Signal, Slot
from workers import ExtractWorker, DownloadWorker, BaseWorker # 워커 클래스 임포트

log = logging.getLogger(__name__)

class TaskManager(QObject):
    # 메인 앱으로 전달할 시그널 정의
    log_updated = Signal(str)            # 포맷된 로그 메시지
    task_progress = Signal(str, int, int)  # task_id, value, max
    task_finished = Signal(str, bool)      # task_id, success
    task_added = Signal(str, str)          # task_id, initial_status_text
    # task_status_changed = Signal(str, str) # task_id, status_text

    def __init__(self, ffmpeg_path):
        super().__init__()
        self.workers = {} # 활성 워커 저장 (task_id: worker_instance)
        self.task_info = {} # 작업 관련 정보 저장 (task_id: {url, save_path, cookie_file, output_file})
        self.ffmpeg_path = ffmpeg_path # FFmpeg 경로 저장
        log.info(f"TaskManager initialized with ffmpeg path: {self.ffmpeg_path}")

    def _generate_task_id(self, title):
        """안전한 파일명을 기반으로 Task ID 생성 (중복 처리 포함)"""
        # 파일명으로 사용 불가능한 문자 제거 또는 변경
        safe_title = "".join([c if c.isalnum() or c in (' ', '-', '_', '.', '[', ']') else '_' for c in title])
        # 너무 길지 않게 자르기 (선택 사항)
        safe_title = safe_title[:100] 
        # 간단한 UUID 추가하여 고유성 보장 (더 안전)
        # task_id = f"{safe_title}_{uuid.uuid4().hex[:8]}"
        # 여기서는 일단 safe_title을 기본 ID로 사용하고, Worker 시작 시 최종 파일명으로 확정
        return safe_title
       
    def _get_unique_output_path(self, save_path, task_id_base):
        """중복되지 않는 최종 파일 경로 생성"""
        output_file = os.path.join(save_path, f"{task_id_base}.mp4")
        counter = 1
        base_name = os.path.splitext(output_file)[0]
        while os.path.exists(output_file):
            output_file = f"{base_name}_{counter}.mp4"
            counter += 1
        return output_file

    @Slot(str, str, str)
    def start_new_task(self, url, save_path, cookie_file):
        """새로운 추출 및 다운로드 작업 시작"""
        temp_task_id = f"Extracting_{uuid.uuid4().hex[:8]}"
        log.info(f"[{temp_task_id}] New task received for URL: {url}")

        self.task_info[temp_task_id] = {
            'url': url,
            'save_path': save_path,
            'cookie_file': cookie_file,
            'status': 'Extracting',
            'output_file': None
        }

        # UI에 작업 추가 알림 (추출 시작 상태)
        self.task_added.emit(temp_task_id, f"{temp_task_id} - Extracting info...")

        extractor = ExtractWorker(temp_task_id, url, cookie_file)
        
        # 워커 시그널 연결
        extractor.signals.log_signal.connect(self._handle_log)
        extractor.signals.result_signal.connect(self._handle_extract_result)
        extractor.signals.finished_signal.connect(self._handle_worker_finished)
        # ExtractWorker는 progress_signal을 사용하지 않음

        self.workers[temp_task_id] = extractor
        extractor.start()
        log.info(f"[{temp_task_id}] ExtractWorker started.")

    @Slot(str, str)
    def _handle_log(self, task_id, message):
        """워커 로그 처리 및 메인 앱으로 전달"""
        # task_id가 유효한지 확인 (이미 완료/취소된 작업일 수 있음)
        if task_id in self.task_info:
            # 필요시 추가 정보 포함하여 포맷팅
            formatted_message = f"[{task_id}] {message}"
            self.log_updated.emit(formatted_message)
        else:
            log.debug(f"Received log for unknown or finished task: {task_id}")

    @Slot(str, dict)
    def _handle_extract_result(self, task_id, result):
        """추출 결과 처리"""
        temp_task_id = task_id 
        logging.info(f"[{task_id}] Handling extract result...")
        
        if task_id not in self.task_info or task_id not in self.workers:
            log.warning(f"Received extract result for unknown or already finished task: {task_id}")
            return

        task_data = self.task_info[task_id]
        
        if result["error"]:
            log.error(f"[{task_id}] Extraction failed: {result['error']}")
            self.log_updated.emit(f"[{task_id}] Extraction failed: {result['error']}")
            # 실패 시 작업 완료 처리 (finished 시그널에서 처리됨)
            # self.task_finished.emit(task_id, False)
            # self._cleanup_task(task_id)
        else:
            log.info(f"[{task_id}] Extraction successful. Title: {result['title']}")
            
            final_task_id_base = self._generate_task_id(result['title'])
            output_file = self._get_unique_output_path(task_data['save_path'], final_task_id_base)
            final_task_id = os.path.basename(output_file)
            log.info(f"[{task_id}] Determined final task ID: {final_task_id}")
            log.info(f"[{task_id}] Determined output file: {output_file}")

            # Task 정보 업데이트 (새 ID로)
            task_data['status'] = 'Downloading'
            task_data['output_file'] = output_file
            # task_info 키 변경 전에 새 키로 데이터 복사
            self.task_info[final_task_id] = task_data 
            # 이전 임시 ID 정보 삭제
            if temp_task_id != final_task_id and temp_task_id in self.task_info:
                 log.debug(f"Removing temporary task info for ID: {temp_task_id}")
                 del self.task_info[temp_task_id]

            # UI 업데이트 (Task ID 변경 알림 - 이전 ID 제거 후 새 ID 추가)
            self.task_finished.emit(temp_task_id, True) # 임시 추출 작업 완료 알림 (UI에서 제거용)
            self.task_added.emit(final_task_id, f"{final_task_id} - Starting download...")

            # DownloadWorker 생성 및 시작
            downloader = DownloadWorker(
                final_task_id, 
                task_data['url'], 
                output_file, 
                self.ffmpeg_path, # 생성자에서 받은 경로 사용
                task_data['cookie_file']
            )

            # 워커 시그널 연결
            downloader.signals.log_signal.connect(self._handle_log)
            downloader.signals.progress_signal.connect(self._handle_progress)
            downloader.signals.finished_signal.connect(self._handle_worker_finished)
            
            # 워커 교체 (새 ID 사용)
            self.workers[final_task_id] = downloader
            # 이전 추출 워커 참조 제거 (worker 딕셔너리에서도 키 변경)
            if temp_task_id != final_task_id and temp_task_id in self.workers:
                 log.debug(f"Removing temporary worker reference for ID: {temp_task_id}")
                 del self.workers[temp_task_id]
                 
            log.info(f"[{final_task_id}] Starting DownloadWorker...")
            downloader.start()
            log.info(f"[{final_task_id}] DownloadWorker started successfully.")

    @Slot(str, int, int)
    def _handle_progress(self, task_id, value, max_value):
        """진행률 처리 및 메인 앱으로 전달"""
        if task_id in self.task_info:
             self.task_progress.emit(task_id, value, max_value)
        else:
             log.debug(f"Received progress for unknown or finished task: {task_id}")

    @Slot(str, bool)
    def _handle_worker_finished(self, task_id, success):
        """워커 종료 처리"""
        log.info(f"[{task_id}] Worker finished signal received. Success: {success}")
        if task_id in self.task_info:
            task_status = self.task_info[task_id].get('status', 'Unknown')
            log.debug(f"Handling finish signal for task {task_id} with status: {task_status}")

            # --- 로직 수정 --- 
            if task_status == 'Extracting':
                if success:
                    # 추출 성공 시에는 _handle_extract_result에서 DownloadWorker를 시작하므로,
                    # 여기서는 워커 참조만 제거하고 완료 처리는 하지 않음.
                    log.info(f"[{task_id}] ExtractWorker finished successfully. Waiting for DownloadWorker.")
                    # 임시 워커 참조 제거
                    if task_id in self.workers:
                         del self.workers[task_id]
                    # Task Info는 _handle_extract_result에서 새 ID로 변경/삭제됨
                else:
                    # 추출 실패 시 작업 완료 처리
                    log.error(f"[{task_id}] Extraction failed or was cancelled.")
                    self.log_updated.emit(f"[{task_id}] Extraction failed or cancelled.")
                    self.task_finished.emit(task_id, False)
                    self._cleanup_task(task_id)
            elif task_status == 'Downloading':
                 # 다운로드 완료/실패 시 최종 완료 처리
                 status_msg = "completed successfully" if success else "failed or was cancelled"
                 log.info(f"[{task_id}] Download {status_msg}. Cleaning up task.")
                 self.log_updated.emit(f"[{task_id}] Download {status_msg}.")
                 self.task_finished.emit(task_id, success)
                 self._cleanup_task(task_id)
            elif task_status == 'Cancelling':
                 # 취소 요청 후 워커가 종료된 경우
                 log.info(f"[{task_id}] Worker finished after cancellation request.")
                 self.log_updated.emit(f"[{task_id}] Task cancelled.")
                 self.task_finished.emit(task_id, False) # 취소는 실패로 간주
                 self._cleanup_task(task_id)
            else: # Unknown 또는 예기치 않은 상태
                 log.warning(f"[{task_id}] Worker finished in unexpected state: {task_status}. Cleaning up.")
                 self.task_finished.emit(task_id, success) # 일단 받은 결과대로 보고
                 self._cleanup_task(task_id)
            # --- 로직 수정 끝 --- 

        else:
            # task_info에 없는 ID (이미 정리되었거나 오류) 처리
            # 임시 추출 ID의 ExtractWorker가 성공적으로 완료된 경우일 수 있음
            if task_id.startswith("Extracting_"):
                log.info(f"Finished signal for completed temporary ExtractWorker: {task_id}. Worker reference removed.")
                if task_id in self.workers:
                    del self.workers[task_id]
            else:
                log.warning(f"Received finish signal for unknown or already cleaned up task: {task_id}")

    def _cleanup_task(self, task_id, remove_info=True):
        """작업 관련 데이터 정리"""
        log.debug(f"Cleaning up task: {task_id}")
        if task_id in self.workers:
            # 스레드가 완전히 종료될 때까지 기다리는 로직 추가 가능 (선택)
            # worker = self.workers[task_id]
            # worker.wait()
            del self.workers[task_id]
        if remove_info and task_id in self.task_info:
            del self.task_info[task_id]
        log.debug(f"Cleanup complete for task: {task_id}")

    @Slot(str)
    def cancel_task(self, task_id):
        """특정 작업 취소 요청"""
        log.info(f"Request received to cancel task: {task_id}")
        if task_id in self.workers:
            worker = self.workers[task_id]
            worker.cancel() # 워커의 cancel 메서드 호출
            # UI 업데이트는 VideoDownloaderApp의 컨텍스트 메뉴 핸들러에서 처리
            self.log_updated.emit(f"[{task_id}] Cancellation requested.")
            # 상태 변경 (선택적)
            if task_id in self.task_info:
                self.task_info[task_id]['status'] = 'Cancelling'
        else:
            log.warning(f"Attempted to cancel non-existent task: {task_id}")

    def get_active_tasks(self):
        """현재 활성 작업 목록 반환 (UI 초기화 등에 사용 가능)"""
        return list(self.task_info.keys())

    def stop_all_tasks(self):
         """앱 종료 시 모든 활성 작업 취소"""
         log.info("Stopping all active tasks...")
         # 리스트 복사 후 순회 (취소 중 딕셔너리 변경 방지)
         task_ids = list(self.workers.keys())
         for task_id in task_ids:
             self.cancel_task(task_id)
         # 모든 스레드가 종료될 때까지 기다리는 로직 추가 가능
