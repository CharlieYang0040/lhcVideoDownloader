import sys
import os
import logging
import logging.handlers
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel,
                               QLineEdit, QPushButton, QFileDialog, QTextEdit, QProgressBar, QHBoxLayout,
                               QMessageBox)
from PySide6.QtCore import Signal, Slot, QThread, Qt
import yt_dlp
from youtube_auth import YouTubeAuthWindow
from config_manager import ConfigManager
import tempfile
import json
import subprocess
import atexit

# 로그 포맷터 설정
log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# 루트 로거 설정 (모든 로거에 적용)
log = logging.getLogger()
log.setLevel(logging.DEBUG) # 로그 레벨 설정

class MyLogger:
    def __init__(self, log_signal):
        self.log_signal = log_signal
        # 클래스 인스턴스별 로거 대신 전역 로거 사용
        # self.logger = logging.getLogger(self.__class__.__name__)
    def debug(self, msg):
        # 표준 로거 사용
        logging.debug(msg)
        # 기존 시그널 방출 유지 (GUI 업데이트용)
        self.log_signal.emit(f"[DEBUG] {msg}")
    def warning(self, msg):
        logging.warning(msg)
        self.log_signal.emit(f"[WARNING] {msg}")
    def error(self, msg):
        logging.error(msg)
        self.log_signal.emit(f"[ERROR] {msg}")

class ExtractWorker(QThread):
    progress_signal = Signal(str)
    result_signal = Signal(dict)

    def __init__(self, url, cookie_file=None):
        super().__init__()
        self.url = url
        self.cookie_file = cookie_file
        
    def run(self):
        try:
            self.progress_signal.emit(f"Attempting to connect to YouTube URL: {self.url}")
            ydl_opts = {
                'quiet': True,
                'no_warnings': True
            }
            
            if self.cookie_file:
                ydl_opts['cookiefile'] = self.cookie_file
                logging.info(f"[ExtractWorker] Using cookie file: {self.cookie_file}")
                
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                self.progress_signal.emit("Retrieving video information...")
                info = ydl.extract_info(self.url, download=False)
                if not info:
                    self.result_signal.emit({"title": "Unknown", "formats": [], "error": "Failed to retrieve video information"})
                    return

                title = info.get('title', f"video_{info.get('id', 'unknown')}")
                self.progress_signal.emit(f"Found title: {title}")

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
                            self.progress_signal.emit(f"Found format: {resolution} ({f.get('ext', 'unknown')})")

                if not formats:
                    self.result_signal.emit({"title": title, "formats": [], "error": "No compatible video formats found"})
                    return

                formats.sort(key=lambda x: int(x['resolution'].replace('p', '')), reverse=True)

                self.result_signal.emit({"title": title, "formats": formats, "error": None})
        except Exception as e:
            self.result_signal.emit({"title": "Unknown", "formats": [], "error": f"Error: {str(e)}"})


class DownloadWorker(QThread):
    progress_signal = Signal(int, int)
    log_signal = Signal(str)
    finished_signal = Signal(bool)

    def __init__(self, url, output_file, ffmpeg_path, cookie_file=None):
        super().__init__()
        self.url = url
        self.output_file = output_file
        self.ffmpeg_path = ffmpeg_path
        self.cookie_file = cookie_file
        self.ydl_opts = {}  # ydl_opts 초기화
        
    def progress_hook(self, d):
        if d['status'] == 'downloading':
            downloaded = d.get('downloaded_bytes', 0)
            total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
            
            if total > 0:  # total이 유효한 값일 때만 진행률 계산
                progress = int((downloaded / total) * 100)
                self.progress_signal.emit(progress, 100)
                
                speed = d.get('speed', 0)
                eta = d.get('eta', 0)
                
                if speed and speed > 1024*1024:  # speed가 None이 아닐 때만 계산
                    speed_str = f"{speed/(1024*1024):.2f} MB/s"
                elif speed and speed > 1024:
                    speed_str = f"{speed/1024:.2f} KB/s"
                else:
                    speed_str = f"{speed:.2f} B/s" if speed else "Unknown speed"
                    
                eta_str = f"{eta}s" if eta else "Unknown"
                self.log_signal.emit(f"다운로드 진행률: {progress}% | 속도: {speed_str} | 남은 시간: {eta_str}")
        
        elif d['status'] == 'started':
            self.log_signal.emit("FFmpeg로 인코딩 중입니다. 잠시 기다려주세요...")
            self.progress_signal.emit(0, 0)
        
        elif d['status'] == 'processing':
            # FFmpeg 처리 상태 표시
            progress = d.get('percent', 0)
            if progress:
                self.progress_signal.emit(int(progress), 100)
                self.log_signal.emit(f"FFmpeg 인코딩 진행률: {int(progress)}%")
        
        elif d['status'] == 'finished':
            self.log_signal.emit("인코딩이 완료되었습니다!")
            self.progress_signal.emit(100, 100)
        
    def run(self):
        try:
            if not os.path.exists(self.ffmpeg_path):
                logging.error(f"FFmpeg not found at {self.ffmpeg_path}")
                self.log_signal.emit(f"Warning: FFmpeg not found at {self.ffmpeg_path}")
                self.finished_signal.emit(False)
                return

            logging.info(f"Using FFmpeg from: {self.ffmpeg_path}")
            logging.info(f"Output file: {self.output_file}")
            self.log_signal.emit("Starting download, conversion, and thumbnail embedding...")

            logger = MyLogger(self.log_signal)
            ydl_opts = {
                'logger': logger,
                'verbose': True,
                'quiet': False,
                'no_warnings': False,
                'format': 'bv*[ext=mp4]+ba*[ext=m4a]/b*[ext=mp4]/bestvideo+bestaudio/best',
                'outtmpl': self.output_file,
                'progress_hooks': [self.progress_hook],
                'merge_output_format': 'mp4',
                'ffmpeg_location': self.ffmpeg_path,
                'force_overwrites': True,
                'writethumbnail': True,
                'concurrent_fragment_downloads': 8,
                'postprocessor_args': {
                    'ffmpeg': [
                        '-loglevel', 'info',
                        '-progress', 'pipe:1'
                    ],
                    'default': [
                        '-c:v', 'libx264',
                        '-preset', 'medium',
                        '-crf', '23',
                        '-c:a', 'aac',
                        '-b:a', '192k',
                        '-movflags', '+faststart'
                    ]
                },
                'postprocessors': [
                    {
                        'key': 'FFmpegVideoConvertor',
                        'preferedformat': 'mp4'
                    },
                    {
                        'key': 'FFmpegMetadata',
                        'add_metadata': True
                    }
                ]
            }

            if self.cookie_file:
                ydl_opts['cookiefile'] = self.cookie_file
                logging.info(f"[DownloadWorker] Using cookie file: {self.cookie_file}")
                
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([self.url])

            logging.info("Download, conversion, metadata insertion, and thumbnail embedding completed successfully!")
            self.log_signal.emit("Download, conversion, metadata insertion, and thumbnail embedding completed successfully!")
            self.finished_signal.emit(True)
        except Exception as e:
            logging.exception("Download failed")
            self.log_signal.emit(f"Download failed: {str(e)}")
            self.finished_signal.emit(False)


class VideoDownloaderApp(QMainWindow):
    update_progress = Signal(int, int)
    log_message = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("YouTube Video Downloader")
        self.setGeometry(200, 200, 600, 450)
        
        # ConfigManager 인스턴스 생성 복구
        self.config_manager = ConfigManager()
        # 임시 쿠키 파일 경로 저장 변수
        self.temp_cookie_file_path = None
        # 종료 시 임시 파일 정리 등록
        atexit.register(self.cleanup_temp_files)
        
        # UI 초기화
        self.main_widget = QWidget()
        self.layout = QVBoxLayout()

        self.url_label = QLabel("YouTube Video URL:")
        self.url_input = QLineEdit()

        self.url_layout = QHBoxLayout()
        self.url_layout.addWidget(self.url_input)
        
        self.paste_btn = QPushButton("붙여넣기")
        self.paste_btn.clicked.connect(self.paste_from_clipboard)
        self.url_layout.addWidget(self.paste_btn)

        self.download_btn = QPushButton("Extract and Download")
        self.download_btn.clicked.connect(self.start_extraction)

        # --- 설정 버튼 영역 복구 --- 
        self.settings_layout = QHBoxLayout()
        
        self.login_status_label = QLabel("로그아웃 상태")
        self.login_status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.settings_layout.addWidget(self.login_status_label)
        
        self.login_btn = QPushButton("YouTube 로그인")
        self.login_btn.clicked.connect(self.show_login_window)
        self.settings_layout.addWidget(self.login_btn)

        self.logout_btn = QPushButton("로그아웃")
        self.logout_btn.clicked.connect(self.logout)
        self.logout_btn.setVisible(False)
        self.settings_layout.addWidget(self.logout_btn)
        
        self.open_config_btn = QPushButton("설정 폴더 열기")
        self.open_config_btn.clicked.connect(self.open_config_folder)
        self.settings_layout.addWidget(self.open_config_btn)
        # --- 설정 버튼 영역 끝 --- 

        self.save_label = QLabel("Save Directory:")
        self.save_path_btn = QPushButton("Choose Folder")
        self.save_path_btn.clicked.connect(self.choose_save_path)
        self.save_path_display = QLabel("Not selected")

        self.progress_bar = QProgressBar()
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)

        self.layout.addWidget(self.url_label)
        self.layout.addLayout(self.url_layout)
        self.layout.addLayout(self.settings_layout)
        self.layout.addWidget(self.save_label)
        self.layout.addWidget(self.save_path_btn)
        self.layout.addWidget(self.save_path_display)
        self.layout.addWidget(self.download_btn)
        self.layout.addWidget(QLabel("Download Progress:"))
        self.layout.addWidget(self.progress_bar)
        self.layout.addWidget(QLabel("Logs:"))
        self.layout.addWidget(self.log_output)
        
        self.main_widget.setLayout(self.layout)
        self.setCentralWidget(self.main_widget)

        self.save_path = os.getcwd()
        self.save_path_display.setText(self.save_path)
        self.video_info = None
        self.extract_thread = None
        self.download_thread = None
        self.auth_window = None

        self.update_progress.connect(self.update_progress_bar)
        self.log_message.connect(self.append_log)

        # 저장된 쿠키 로드 시도
        self.load_and_prepare_cookies()
    
    def load_and_prepare_cookies(self):
        """저장된 쿠키를 로드하고 임시 파일로 준비"""
        logging.info("저장된 쿠키 로드 시도...")
        try:
            # ConfigManager에서 복호화된 Netscape 문자열 로드
            netscape_cookie_string = self.config_manager.load_cookies()
            if netscape_cookie_string:
                # 기존 임시 파일 정리
                self.cleanup_temp_files()
                
                # 새 임시 파일 생성 (delete=False 중요!)
                temp_cookie_file = tempfile.NamedTemporaryFile(
                    mode='w', 
                    suffix='.txt', 
                    delete=False, # 프로세스 종료 후에도 유지되도록 함
                    encoding='utf-8'
                )
                temp_cookie_file.write(netscape_cookie_string)
                temp_cookie_file.close() # 파일 닫기 (경로만 사용)
                
                self.temp_cookie_file_path = temp_cookie_file.name
                logging.info(f"임시 쿠키 파일 생성 완료: {self.temp_cookie_file_path}")
                self.update_login_status(logged_in=True)
            else:
                logging.info("저장된 쿠키 없음.")
                self.update_login_status(logged_in=False)
        except Exception as e:
            logging.exception("쿠키 로드/준비 중 오류 발생")
            self.update_login_status(logged_in=False)
            # 오류 시 임시 파일 경로 초기화
            self.temp_cookie_file_path = None 

    def cleanup_temp_files(self):
        """앱 종료 시 임시 쿠키 파일 정리"""
        if self.temp_cookie_file_path and os.path.exists(self.temp_cookie_file_path):
            try:
                os.remove(self.temp_cookie_file_path)
                logging.info(f"임시 쿠키 파일 삭제: {self.temp_cookie_file_path}")
                self.temp_cookie_file_path = None
            except Exception as e:
                logging.error(f"임시 쿠키 파일 삭제 오류: {e}")
                
    def update_login_status(self, logged_in):
        """로그인 상태에 따라 UI 업데이트"""
        if logged_in:
            self.login_status_label.setText("로그인됨")
            self.login_btn.setText("다시 로그인")
            self.logout_btn.setVisible(True)
        else:
            self.login_status_label.setText("로그아웃 상태")
            self.login_btn.setText("YouTube 로그인")
            self.logout_btn.setVisible(False)
            # 로그아웃 시 임시 파일 경로도 초기화
            self.cleanup_temp_files() 

    def choose_save_path(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Save Directory")
        if folder:
            self.save_path = folder
            self.save_path_display.setText(folder)

    @Slot()
    def start_extraction(self):
        video_url = self.url_input.text()
        if not video_url:
            self.append_log("Please enter a valid YouTube video URL.")
            return
        if not self.save_path:
            self.append_log("Please select a save directory.")
            return

        self.append_log("Extracting video information...")
        if self.extract_thread and self.extract_thread.isRunning():
            self.append_log("Extraction is already running.")
            return

        self.extract_thread = ExtractWorker(video_url, cookie_file=self.temp_cookie_file_path)
        self.extract_thread.progress_signal.connect(self.append_log)
        self.extract_thread.result_signal.connect(self.handle_extract_result)
        self.extract_thread.start()

    @Slot(dict)
    def handle_extract_result(self, result):
        self.video_info = result
        if self.video_info["error"]:
            logging.error(f"Error during extraction: {self.video_info['error']}")
            self.append_log(f"Error during extraction: {self.video_info['error']}")
            return

        logging.info(f"Title: {self.video_info['title']}")
        self.append_log(f"Title: {self.video_info['title']}")
        if not self.video_info["formats"]:
            logging.warning("No available formats found.")
            self.append_log("No available formats found.")
            return

        self.append_log("Available Resolutions:")
        for fmt in self.video_info["formats"]:
            self.append_log(f"- {fmt['resolution']}")

        safe_title = "".join([
            c if c.isalnum() or c in (' ', '-', '_', '.', '[', ']') else '_'
            for c in self.video_info['title']
        ])

        output_file = os.path.join(self.save_path, f"{safe_title}.mp4")

        counter = 1
        base_name = os.path.splitext(output_file)[0]
        while os.path.exists(output_file):
            output_file = f"{base_name}_{counter}.mp4"
            counter += 1

        if getattr(sys, 'frozen', False):
            ffmpeg_path = os.path.join(sys._MEIPASS, 'libs', 'ffmpeg-7.1-full_build', 'bin', 'ffmpeg.exe')
            logging.info(f"임시 디렉토리에서 FFmpeg 사용: {ffmpeg_path}")
            self.append_log(f"임시 디렉토리에서 FFmpeg 사용: {ffmpeg_path}")
        else:
            script_dir = os.path.dirname(__file__)
            ffmpeg_path = os.path.join(script_dir, 'libs', 'ffmpeg-7.1-full_build', 'bin', 'ffmpeg.exe')
            logging.info(f"로컬 FFmpeg 사용: {ffmpeg_path}")
            self.append_log(f"로컬 FFmpeg 사용: {ffmpeg_path}")

        if not os.path.exists(ffmpeg_path):
            error_msg = f"FFmpeg를 찾을 수 없습니다: {ffmpeg_path}"
            logging.error(error_msg)
            self.append_log(error_msg)
            QMessageBox.critical(self, "오류", error_msg)
            return

        self.download_thread = DownloadWorker(
            self.url_input.text(),
            output_file,
            ffmpeg_path,
            cookie_file=self.temp_cookie_file_path
        )
        
        self.download_thread.progress_signal.connect(self.update_progress_bar)
        self.download_thread.log_signal.connect(self.append_log)
        self.download_thread.finished_signal.connect(self.download_finished)
        self.download_thread.start()

    @Slot(bool)
    def download_finished(self, success):
        if success:
            logging.info("Download process finished successfully.")
            self.append_log("Download process finished successfully.")
        else:
            logging.warning("Download process ended with an error or was incomplete.")
            self.append_log("Download process ended with an error or was incomplete.")

    @Slot(int, int)
    def update_progress_bar(self, value, max_value):
        self.progress_bar.setMaximum(max_value)
        self.progress_bar.setValue(value)

    @Slot(str)
    def append_log(self, message):
        # GUI 로그창 업데이트
        self.log_output.append(message)
        # 파일 로그 기록 (기존 로직 유지)
        logging.info(message.replace('[DEBUG] ', '').replace('[WARNING] ', '').replace('[ERROR] ', ''))

    def paste_from_clipboard(self):
        clipboard = QApplication.clipboard()
        self.url_input.setText(clipboard.text())

    def show_login_window(self):
        """YouTube 로그인 창을 표시"""
        logging.info("로그인 창 표시 요청")
        if self.auth_window and self.auth_window.isVisible():
            logging.info("로그인 창이 이미 열려 있음. 활성화.")
            self.auth_window.activateWindow()
            self.auth_window.raise_()
            return

        try:
            logging.info("YouTubeAuthWindow 인스턴스 생성 시도...")
            self.auth_window = YouTubeAuthWindow()
            self.auth_window.login_completed.connect(self.handle_login_completed)
            logging.info("YouTubeAuthWindow 생성 및 시그널 연결 완료.")
        except Exception as e:
            logging.exception("YouTubeAuthWindow 생성 중 오류")
            self.append_log(f"로그인 창 생성 오류: {e}")
            QMessageBox.critical(self, "로그인 오류", f"로그인 창을 생성하는 중 오류가 발생했습니다:\n{e}")
            self.auth_window = None
    
    @Slot()
    def handle_login_completed(self):
        """로그인이 완료되면 쿠키를 다시 로드하고 상태 업데이트"""
        # 슬롯 실행 시작 로깅
        logging.info("[App] handle_login_completed slot triggered.") 
        self.append_log("YouTube 로그인이 완료되었습니다.")
        # 로그인 성공 후 쿠키 로드 및 임시 파일 재생성
        self.load_and_prepare_cookies()

    @Slot()
    def logout(self):
        """로그아웃 처리: 저장된 쿠키 삭제 및 상태 업데이트"""
        logging.info("로그아웃 요청")
        self.config_manager.delete_cookies()
        self.update_login_status(logged_in=False)
        self.append_log("로그아웃 되었습니다.")

    def open_config_folder(self):
        """설정 폴더(쿠키 저장 폴더)를 파일 탐색기로 엽니다"""
        config_path = self.config_manager.cookies_dir 
        logging.info(f"설정 폴더 열기 요청: {config_path}")
        try:
            os.makedirs(config_path, exist_ok=True)
            if os.name == 'nt':
                os.startfile(config_path)
            elif os.name == 'posix':
                subprocess.run(['xdg-open', config_path])
            self.append_log(f"설정 폴더를 열었습니다: {config_path}")
        except Exception as e:
            logging.exception("설정 폴더 열기 오류")
            self.append_log(f"설정 폴더를 여는 중 오류가 발생했습니다: {e}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VideoDownloaderApp()
    window.show()
    sys.exit(app.exec())
