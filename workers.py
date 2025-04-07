import logging
import os
from PySide6.QtCore import Signal, QThread, QMutex, QWaitCondition, QObject
import yt_dlp
import time

log = logging.getLogger(__name__)

class MyLogger:
    def __init__(self, task_id):
        self.task_id = task_id
        
    def debug(self, msg):
        log.debug(f"[{self.task_id}] {msg}")
    def warning(self, msg):
        log.warning(f"[{self.task_id}] {msg}")
    def error(self, msg):
        log.error(f"[{self.task_id}] {msg}")

class WorkerSignals(QObject):
    # task_id를 포함하도록 시그널 수정
    progress_signal = Signal(str, int, int)  # task_id, value, max
    log_signal = Signal(str, str)            # task_id, message
    result_signal = Signal(str, dict)        # task_id, result_dict
    finished_signal = Signal(str, bool)      # task_id, success

class BaseWorker(QThread):
    def __init__(self, task_id):
        super().__init__()
        self.task_id = task_id
        self.signals = WorkerSignals()
        self._is_cancelled = False
        self._mutex = QMutex()
        self._condition = QWaitCondition()

    def cancel(self):
        log.info(f"[{self.task_id}] Cancellation requested.")
        with self._mutex:
            self._is_cancelled = True
        # yt-dlp 프로세스가 실행 중일 수 있으므로, 관련 로직 필요 (추후 추가)

    def run(self):
        raise NotImplementedError("Subclasses must implement the run method.")

class ExtractWorker(BaseWorker):
    def __init__(self, task_id, url, cookie_file=None):
        super().__init__(task_id)
        self.url = url
        self.cookie_file = cookie_file
        
    def run(self):
        log.info(f"[{self.task_id}] Starting extraction for URL: {self.url}")
        try:
            self.signals.log_signal.emit(self.task_id, f"Attempting to connect to YouTube URL: {self.url}")
            ydl_opts = {
                'quiet': True,
                'no_warnings': True
            }
            
            if self.cookie_file:
                ydl_opts['cookiefile'] = self.cookie_file
                log.info(f"[{self.task_id}] Using cookie file: {self.cookie_file}")
            
            # 취소 확인 지점 추가 (예시)
            if self._is_cancelled:
                 log.info(f"[{self.task_id}] Extraction cancelled before starting yt-dlp.")
                 self.signals.finished_signal.emit(self.task_id, False)
                 return
                 
            # yt-dlp 인스턴스 생성
            ydl = yt_dlp.YoutubeDL(ydl_opts)

            self.signals.log_signal.emit(self.task_id, "Retrieving video information...")
            
            # 정보 추출 (여기서도 취소 가능하도록 yt-dlp 옵션 탐색 필요)
            info = ydl.extract_info(self.url, download=False) 
            
            # 취소 확인
            if self._is_cancelled:
                 log.info(f"[{self.task_id}] Extraction cancelled after retrieving info.")
                 self.signals.finished_signal.emit(self.task_id, False)
                 return

            if not info:
                error_msg = "Failed to retrieve video information"
                log.error(f"[{self.task_id}] {error_msg}")
                self.signals.result_signal.emit(self.task_id, {"title": "Unknown", "formats": [], "error": error_msg})
                self.signals.finished_signal.emit(self.task_id, False)
                return

            title = info.get('title', f"video_{info.get('id', 'unknown')}")
            self.signals.log_signal.emit(self.task_id, f"Found title: {title}")

            seen_resolutions = set()
            formats = []
            
            for f in info['formats']:
                if (f.get('height') and f.get('vcodec') != 'none'):
                    resolution = f'{f.get("height")}p'
                    if resolution not in seen_resolutions:
                        seen_resolutions.add(resolution)
                        formats.append({
                            'resolution': resolution,
                            'format_id': f['format_id'],
                            'ext': f.get('ext', ''),
                            'vcodec': f.get('vcodec', ''),
                            'acodec': f.get('acodec', '')
                        })
                        self.signals.log_signal.emit(self.task_id, f"Found format: {resolution} ({f.get('ext', 'unknown')})")

            if not formats:
                error_msg = "No compatible video formats found"
                log.warning(f"[{self.task_id}] {error_msg}")
                self.signals.result_signal.emit(self.task_id, {"title": title, "formats": [], "error": error_msg})
                self.signals.finished_signal.emit(self.task_id, False)
                return

            formats.sort(key=lambda x: int(x['resolution'].replace('p', '')), reverse=True)
            
            log.info(f"[{self.task_id}] Extraction successful.")
            self.signals.result_signal.emit(self.task_id, {"title": title, "formats": formats, "error": None})
            self.signals.finished_signal.emit(self.task_id, True) # 추출 성공 시 True

        except Exception as e:
            if self._is_cancelled: # 취소로 인한 예외인지 확인 (어려울 수 있음)
                 log.warning(f"[{self.task_id}] Extraction likely cancelled during operation: {e}")
                 self.signals.result_signal.emit(self.task_id, {"title": "Unknown", "formats": [], "error": "Extraction cancelled"})
                 self.signals.finished_signal.emit(self.task_id, False)
            else:
                log.exception(f"[{self.task_id}] Error during extraction")
                self.signals.result_signal.emit(self.task_id, {"title": "Unknown", "formats": [], "error": f"Error: {str(e)}"})
                self.signals.finished_signal.emit(self.task_id, False)

class DownloadWorker(BaseWorker):
    def __init__(self, task_id, url, output_file, ffmpeg_path, cookie_file=None):
        super().__init__(task_id)
        self.url = url
        self.output_file = output_file
        self.ffmpeg_path = ffmpeg_path
        self.cookie_file = cookie_file
        self.ydl = None # yt-dlp 인스턴스 저장용

    # progress_hook 수정: 시그널에 task_id 전달
    def progress_hook(self, d):
        # 취소 확인
        if self._is_cancelled:
            # yt-dlp에 취소를 알리는 방법 필요 (현재는 훅 중단만 가능)
            log.info(f"[{self.task_id}] Download cancelled during progress hook.")
            raise yt_dlp.utils.DownloadCancelled() # yt-dlp에 취소 시도

        if d['status'] == 'downloading':
            downloaded = d.get('downloaded_bytes', 0)
            total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
            
            if total > 0:
                progress = int((downloaded / total) * 100)
                self.signals.progress_signal.emit(self.task_id, progress, 100)
                
                speed = d.get('speed', 0)
                eta = d.get('eta', 0)
                
                if speed and speed > 1024*1024:
                    speed_str = f"{speed/(1024*1024):.2f} MB/s"
                elif speed and speed > 1024:
                    speed_str = f"{speed/1024:.2f} KB/s"
                else:
                    speed_str = f"{speed:.2f} B/s" if speed else "Unknown speed"
                    
                eta_str = f"{eta}s" if eta else "Unknown"
                # 로그 시그널에는 포맷된 메시지 전달
                self.signals.log_signal.emit(self.task_id, f"다운로드 진행률: {progress}% | 속도: {speed_str} | 남은 시간: {eta_str}")
        
        elif d['status'] == 'started': # yt-dlp 2023.11.16 이후 'started' 대신 'processing' 사용 가능성 있음
            self.signals.log_signal.emit(self.task_id, "FFmpeg 처리 시작...")
            self.signals.progress_signal.emit(self.task_id, 0, 0) # 불확정 진행률
        
        elif d['status'] == 'processing': # FFmpeg 처리 (새 버전 yt-dlp)
            progress = d.get('fragment_index') # 예시, 실제 키 다를 수 있음
            total = d.get('fragment_count')
            if progress and total:
                 percent = int((progress/total)*100)
                 self.signals.progress_signal.emit(self.task_id, percent, 100)
                 self.signals.log_signal.emit(self.task_id, f"FFmpeg 처리 진행률: {percent}%")
            else:
                 self.signals.progress_signal.emit(self.task_id, 0, 0) # 불확정 진행률
                 self.signals.log_signal.emit(self.task_id, f"FFmpeg 처리 중... ({d.get('progress', '진행 정보 없음')})")

        elif d['status'] == 'finished':
            self.signals.log_signal.emit(self.task_id, "다운로드/처리가 완료되었습니다!")
            self.signals.progress_signal.emit(self.task_id, 100, 100)
        
    def run(self):
        log.info(f"[{self.task_id}] Starting download for URL: {self.url}")
        try:
            if not os.path.exists(self.ffmpeg_path):
                error_msg = f"FFmpeg not found at {self.ffmpeg_path}"
                log.error(f"[{self.task_id}] {error_msg}")
                self.signals.log_signal.emit(self.task_id, f"Warning: FFmpeg not found at {self.ffmpeg_path}")
                self.signals.finished_signal.emit(self.task_id, False)
                return

            log.info(f"[{self.task_id}] Using FFmpeg from: {self.ffmpeg_path}")
            log.info(f"[{self.task_id}] Output file: {self.output_file}")
            self.signals.log_signal.emit(self.task_id, "Starting download, conversion, and thumbnail embedding...")

            logger = MyLogger(self.task_id)
            
            ydl_opts = {
                'logger': logger,
                'verbose': True,
                'quiet': False,
                'no_warnings': False,
                'format': 'bv*[ext=mp4]+ba*[ext=m4a]/b*[ext=mp4]/bestvideo+bestaudio/best',
                'no_mtime': True,
                'outtmpl': self.output_file,
                'progress_hooks': [self.progress_hook],
                'merge_output_format': 'mp4',
                'ffmpeg_location': self.ffmpeg_path,
                'force_overwrites': True,
                'writethumbnail': True,
                'concurrent_fragment_downloads': 8, # 동시 다운로드 조각 수
                 # 'external_downloader': 'aria2c', # aria2c 사용 시 (선택)
                 # 'external_downloader_args': {'aria2c': ['-x', '16', '-s', '16', '-k', '1M']}, # aria2c 옵션
                'postprocessor_args': {
                    'ffmpeg': [
                        '-loglevel', 'info', # 또는 'warning', 'error'
                        '-progress', 'pipe:1' # FFmpeg 진행률 파싱용
                    ],
                    'default': [ # 메타데이터/썸네일용 후처리기에는 적용되지 않음
                        '-c:v', 'libx264', '-preset', 'medium', '-crf', '23',
                        '-c:a', 'aac', '-b:a', '192k',
                        '-movflags', '+faststart'
                    ]
                },
                'postprocessors': [
                    {'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'},
                    {'key': 'FFmpegMetadata', 'add_metadata': True},
                    # EmbedThumbnail 후처리기는 writethumbnail 옵션과 함께 자동 추가됨
                    # {'key': 'EmbedThumbnail', 'already_have_thumbnail': False}, 
                ],
                # 취소 지원을 위한 옵션 (yt-dlp 버전에 따라 동작 다름)
                'ignoreerrors': False, # 오류 발생 시 중단
                # 'break_on_reject': True, # 거부된 형식 만나면 중단 (효과 제한적)
            }

            if self.cookie_file:
                ydl_opts['cookiefile'] = self.cookie_file
                log.info(f"[{self.task_id}] Using cookie file: {self.cookie_file}")

            # yt-dlp 인스턴스 생성
            self.ydl = yt_dlp.YoutubeDL(ydl_opts)
            
            # 취소 확인
            if self._is_cancelled:
                 log.info(f"[{self.task_id}] Download cancelled before starting download.")
                 self.signals.finished_signal.emit(self.task_id, False)
                 return

            # 다운로드 시작
            self.ydl.download([self.url])
            
            # 취소 확인 (download() 이후)
            if self._is_cancelled:
                 log.info(f"[{self.task_id}] Download likely cancelled during operation (after ydl.download call).")
                 # 파일이 부분적으로 생성되었을 수 있음
                 self.signals.finished_signal.emit(self.task_id, False)
                 return

            log.info(f"[{self.task_id}] Download process finished successfully!")
            self.signals.log_signal.emit(self.task_id, "Download process finished successfully!")
            self.signals.finished_signal.emit(self.task_id, True)

        except yt_dlp.utils.DownloadCancelled:
             log.warning(f"[{self.task_id}] Download explicitly cancelled by progress hook.")
             self.signals.log_signal.emit(self.task_id, "Download cancelled.")
             self.signals.finished_signal.emit(self.task_id, False)
        except Exception as e:
            # 예외 유형 확인하여 취소 관련 예외인지 판단 (어려움)
            if self._is_cancelled:
                 log.warning(f"[{self.task_id}] Download likely cancelled, exception occurred: {e}")
                 self.signals.log_signal.emit(self.task_id, f"Download cancelled: {e}")
                 self.signals.finished_signal.emit(self.task_id, False)
            else:
                log.exception(f"[{self.task_id}] Download failed")
                self.signals.log_signal.emit(self.task_id, f"Download failed: {str(e)}")
                self.signals.finished_signal.emit(self.task_id, False)
        finally:
            self.ydl = None # 참조 정리
