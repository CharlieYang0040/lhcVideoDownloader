import sys
import os
import logging
import logging.handlers
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel,
                               QLineEdit, QPushButton, QFileDialog, QTextEdit, QProgressBar, QHBoxLayout,
                               QMessageBox, QListWidget, QListWidgetItem, QDialog, QMenu)
from PySide6.QtCore import Signal, Slot, QThread, Qt
import yt_dlp
from youtube_auth import YouTubeAuthWindow
from config_manager import ConfigManager
import tempfile
import json
import subprocess
import atexit
from workers import ExtractWorker, DownloadWorker, BaseWorker
from task_manager import TaskManager

# 로그 포맷터 설정
log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# 루트 로거 설정 (모든 로거에 적용)
log = logging.getLogger()
log.setLevel(logging.DEBUG) # 로그 레벨 설정

class VideoDownloaderApp(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # --- 로깅 설정 (가장 먼저 수행) ---
        try:
            log_dir_name = "logs"
            if getattr(sys, 'frozen', False):
                app_dir = os.path.dirname(sys.executable)
            else:
                # __file__은 현재 파일 경로를 나타냄
                app_dir = os.path.dirname(os.path.abspath(__file__)) 
            
            log_dir = os.path.join(app_dir, log_dir_name)
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, 'app.log')

            # 핸들러 중복 추가 방지
            if not any(isinstance(h, logging.handlers.RotatingFileHandler) and h.baseFilename == log_file for h in log.handlers):
                file_handler = logging.handlers.RotatingFileHandler(
                    log_file, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8')
                file_handler.setFormatter(log_formatter)
                file_handler.setLevel(logging.DEBUG)
                log.addHandler(file_handler)
                print(f"File handler added for: {log_file}") # 핸들러 추가 확인용 출력
            else:
                print(f"File handler for {log_file} already exists.")

            logging.info("--- Application Started ---")
            logging.info(f"Log file path: {log_file}")
        except Exception as e:
            print(f"Error setting up logging: {e}") 
        # --- 로깅 설정 끝 ---
        
        self.setWindowTitle("YouTube Video Downloader")
        self.setGeometry(200, 200, 700, 550)
        
        self.config_manager = ConfigManager()
        self.temp_cookie_file_path = None
        atexit.register(self.cleanup_temp_files)
        atexit.register(self.save_current_settings)

        # --- FFmpeg 경로 결정 --- 
        self.ffmpeg_path = self._determine_ffmpeg_path()
        if not self.ffmpeg_path or not os.path.exists(self.ffmpeg_path):
             error_msg = f"FFmpeg를 찾을 수 없습니다. 예상 경로: {self.ffmpeg_path if self.ffmpeg_path else '경로 미설정'}"
             logging.error(error_msg)
             QMessageBox.critical(self, "치명적 오류", f"{error_msg}\n프로그램을 종료합니다.")
             sys.exit(1) # FFmpeg 없으면 종료
        logging.info(f"Using FFmpeg at: {self.ffmpeg_path}")

        # --- Task Manager 초기화 --- 
        # TaskManager 생성 시 ffmpeg_path 전달
        self.task_manager = TaskManager(ffmpeg_path=self.ffmpeg_path)
        self.task_manager.log_updated.connect(self.append_log)
        self.task_manager.task_progress.connect(self.update_task_progress)
        self.task_manager.task_finished.connect(self.handle_task_finished)
        # task_added 시그널 연결 추가
        self.task_manager.task_added.connect(self.add_task_to_list)
        
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

        # --- 다운로드 목록 UI 추가 --- 
        self.task_list_label = QLabel("Active Downloads:")
        self.task_list_widget = QListWidget()
        self.task_list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.task_list_widget.customContextMenuRequested.connect(self.show_task_context_menu) 

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)

        self.layout.addWidget(self.url_label)
        self.layout.addLayout(self.url_layout)
        self.layout.addLayout(self.settings_layout)
        self.layout.addWidget(self.save_label)
        self.layout.addWidget(self.save_path_btn)
        self.layout.addWidget(self.save_path_display)
        self.layout.addWidget(self.download_btn)
        self.layout.addWidget(self.task_list_label)
        self.layout.addWidget(self.task_list_widget)
        self.layout.addWidget(QLabel("Logs:"))
        self.layout.addWidget(self.log_output)
        
        self.main_widget.setLayout(self.layout)
        self.setCentralWidget(self.main_widget)

        # 저장 경로 초기화 (설정 파일 로드 시도)
        loaded_save_path = self.config_manager.load_setting('save_path', default=os.getcwd())
        # 로드된 경로가 유효한지 확인
        if os.path.isdir(loaded_save_path):
            self.save_path = loaded_save_path
            logging.info(f"이전 저장 경로 로드 성공: {self.save_path}")
        else:
            self.save_path = os.getcwd() # 유효하지 않으면 기본 경로 사용
            logging.warning(f"이전 저장 경로({loaded_save_path})가 유효하지 않아 기본 경로({self.save_path})를 사용합니다.")
        self.save_path_display.setText(self.save_path)
        
        self.auth_window = None

        self.load_and_prepare_cookies()
    
    def _determine_ffmpeg_path(self):
        if getattr(sys, 'frozen', False):
            base_path = getattr(sys, '_MEIPASS', os.path.abspath("."))
            ffmpeg_path = os.path.join(base_path, 'libs', 'ffmpeg-7.1-full_build', 'bin', 'ffmpeg.exe')
        else:
            script_dir = os.path.dirname(__file__)
            ffmpeg_path = os.path.join(script_dir, 'libs', 'ffmpeg-7.1-full_build', 'bin', 'ffmpeg.exe')
        return ffmpeg_path

    def save_current_settings(self):
        """앱 종료 시 현재 설정을 저장"""
        if self.save_path:
            logging.info(f"앱 종료, 현재 저장 경로 저장: {self.save_path}")
            self.config_manager.save_setting('save_path', self.save_path)

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
        # 기존 경로를 시작 지점으로 사용
        start_dir = self.save_path if os.path.isdir(self.save_path) else os.getcwd()
        folder = QFileDialog.getExistingDirectory(self, "Select Save Directory", dir=start_dir)
        if folder:
            self.save_path = folder
            self.save_path_display.setText(folder)
            # 경로 변경 시 즉시 저장 (선택 사항)
            # self.config_manager.save_setting('save_path', self.save_path)

    @Slot()
    def start_extraction(self):
        video_url = self.url_input.text()
        if not video_url:
            self.append_log("Please enter a valid YouTube video URL.")
            return
        if not self.save_path:
            self.append_log("Please select a save directory.")
            return

        logging.info(f"Requesting extraction for URL: {video_url}")
        self.task_manager.start_new_task(video_url, self.save_path, self.temp_cookie_file_path)

    @Slot(str, int, int)
    def update_task_progress(self, task_id, value, max_value):
        # task_id를 UserRole 데이터로 검색
        for i in range(self.task_list_widget.count()):
            item = self.task_list_widget.item(i)
            if item.data(Qt.UserRole) == task_id:
                # 진행률 텍스트 업데이트
                item.setText(f"{task_id} - {value}% ({value}/{max_value})")
                return # 찾았으면 종료
        # 아이템이 없는 경우 (이론상 add_task_to_list가 먼저 호출되어야 함)
        logging.warning(f"Progress update received for item not in list: {task_id}")
        # 필요시 여기서 아이템을 추가할 수도 있음
        # item = QListWidgetItem(f"{task_id} - {value}% ({value}/{max_value})")
        # item.setData(Qt.UserRole, task_id)
        # self.task_list_widget.addItem(item)

    @Slot(str, bool)
    def handle_task_finished(self, task_id, success):
        logging.info(f"Handling finished task in UI: {task_id}, Success: {success}")
        # task_id를 UserRole 데이터로 검색
        for i in range(self.task_list_widget.count()):
            item = self.task_list_widget.item(i)
            if item.data(Qt.UserRole) == task_id:
                status = "Completed" if success else "Failed"
                item.setText(f"{task_id} - {status}")
                 # 성공/실패에 따라 아이콘이나 색상 변경 등 추가 가능
                # if not success:
                #    item.setForeground(Qt.red)
                return # 찾았으면 종료
        logging.warning(f"Finished signal received for item not in list: {task_id}")

    @Slot(str)
    def append_log(self, message):
        self.log_output.append(message)

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
        logging.info("[App] handle_login_completed slot triggered.") 
        self.append_log("YouTube 로그인이 완료되었습니다.")
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

    def show_task_context_menu(self, position):
        item = self.task_list_widget.itemAt(position)
        if item:
            task_id = item.data(Qt.UserRole)
            if task_id:
                menu = QMenu()
                cancel_action = menu.addAction("Cancel Task")
                action = menu.exec(self.task_list_widget.mapToGlobal(position))
                if action == cancel_action:
                    logging.info(f"Requesting cancellation for task: {task_id}")
                    self.task_manager.cancel_task(task_id)
                    item.setText(f"{task_id} - Cancelling...")

    @Slot(str, str)
    def add_task_to_list(self, task_id, initial_status_text):
        """새 작업을 다운로드 목록에 추가"""
        # 중복 추가 방지 (ID가 동일한 아이템이 이미 있는지 확인)
        items = self.task_list_widget.findItems(task_id, Qt.MatchExactly)
        if not items:
            item = QListWidgetItem(initial_status_text) # 초기 텍스트 설정
            item.setData(Qt.UserRole, task_id) # UserRole에 task_id 저장
            self.task_list_widget.addItem(item)
            logging.info(f"Task added to list: {task_id}")
        else:
            # 이미 있다면 텍스트 업데이트 (예: 추출->다운로드 상태 변경 시)
             items[0].setText(initial_status_text)
             logging.info(f"Task status updated in list: {task_id}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VideoDownloaderApp()
    window.show()
    sys.exit(app.exec())
