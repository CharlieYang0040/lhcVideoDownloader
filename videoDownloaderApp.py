import sys
import os
import logging
import logging.handlers
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QTextEdit,
    QProgressBar,
    QHBoxLayout,
    QMessageBox,
    QListWidget,
    QListWidgetItem,
    QDialog,
    QMenu,
)
from PySide6.QtCore import Signal, Slot, QThread, Qt, QObject
import yt_dlp
from youtube_auth import YouTubeAuthWindow
from config_manager import ConfigManager
import tempfile
import json
import subprocess
import atexit
from workers import ExtractWorker, DownloadWorker, BaseWorker
from task_manager import TaskManager
from logging_config import setup_logging, LOG_FORMAT


# --- 로깅 시그널 발생기 --- (QObject 상속)
class LogSignalEmitter(QObject):
    """로그 메시지 수신 시 시그널을 발생시키는 QObject."""
    log_received = Signal(str)

    def emit_log(self, msg):
        """받은 로그 메시지로 시그널 발생."""
        self.log_received.emit(msg)


# --- QTextEdit 핸들러 --- (logging.Handler 상속)
class QTextEditHandler(logging.Handler):
    """로그 메시지를 LogSignalEmitter를 통해 시그널로 전달하는 핸들러."""
    def __init__(self, signal_emitter: LogSignalEmitter):
        """QTextEditHandler 초기화

        Args:
            signal_emitter (LogSignalEmitter): 로그 시그널을 발생시킬 객체.
        """
        super().__init__()
        self.signal_emitter = signal_emitter
        self.setFormatter(logging.Formatter(LOG_FORMAT))

    def emit(self, record):
        """로그 레코드를 포맷하고 signal_emitter를 통해 시그널 발생 요청."""
        # 무한 재귀 방지 (handleError가 다시 로깅을 시도할 경우)
        if record.name == __name__: # 이 핸들러 자체에서 발생한 로그는 무시 (선택적)
             return
        try:
            msg = self.format(record)
            self.signal_emitter.emit_log(msg)
        except Exception:
            # handleError 호출 시 추가적인 로깅 오류를 피하기 위해
            # stderr로 직접 출력하거나 다른 안전한 방법 사용 고려
            import traceback
            traceback.print_exc(file=sys.stderr)
            # self.handleError(record) # 재귀 호출 위험으로 주석 처리

# --- 핸들러 정의 끝 ---


class VideoDownloaderApp(QMainWindow):
    """메인 애플리케이션 윈도우 클래스."""
    def __init__(self):
        """VideoDownloaderApp 초기화 및 UI 설정"""
        super().__init__()

        # 1. 기본 윈도우 설정
        self.setWindowTitle("YouTube Video Downloader")
        self.setGeometry(200, 200, 700, 550)

        # 2. 비즈니스 로직 및 설정 초기화
        self._init_backend()

        # 3. UI 초기화 및 설정
        self._init_ui()
        self._setup_layout()
        self._connect_signals()

        # 4. 초기 상태 설정 (로그인, 저장 경로 등)
        self._load_initial_settings()

    def _init_backend(self):
        """설정 관리자, Task Manager 등 백엔드 로직 초기화."""
        self.config_manager = ConfigManager()
        self.temp_cookie_file_path = None
        atexit.register(self.cleanup_temp_files)
        atexit.register(self.save_current_settings)

        # FFmpeg 경로 확인
        self.ffmpeg_path = self.config_manager.ffmpeg_path
        if not self.ffmpeg_path:
            # ConfigManager에서 이미 오류 로그를 남김
            QMessageBox.critical(
                self,
                "치명적 오류",
                "FFmpeg를 찾을 수 없습니다. 프로그램 설정을 확인하거나 FFmpeg를 올바른 위치에 설치해주세요.\n프로그램을 종료합니다.",
            )
            sys.exit(1)

        # Task Manager 초기화
        self.task_manager = TaskManager(ffmpeg_path=self.ffmpeg_path)
        self.auth_window = None  # 로그인 창 인스턴스

    def _init_ui(self):
        """UI 위젯 생성 및 초기 설정."""
        self.main_widget = QWidget()

        # URL 입력 영역
        self.url_label = QLabel("YouTube Video URL:")
        self.url_input = QLineEdit()
        self.paste_btn = QPushButton("붙여넣기")

        # 다운로드 버튼
        self.download_btn = QPushButton("Extract and Download")

        # 설정 버튼 영역
        self.login_status_label = QLabel("로그아웃 상태")
        self.login_status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.login_btn = QPushButton("YouTube 로그인")
        self.logout_btn = QPushButton("로그아웃")
        self.logout_btn.setVisible(False)  # 초기 상태는 숨김
        self.open_config_btn = QPushButton("설정 폴더 열기")

        # 저장 경로 영역
        self.save_label = QLabel("Save Directory:")
        self.save_path_btn = QPushButton("Choose Folder")
        self.save_path_display = QLabel("Not selected")

        # 다운로드 목록
        self.task_list_label = QLabel("Active Downloads:")
        self.task_list_widget = QListWidget()
        self.task_list_widget.setContextMenuPolicy(Qt.CustomContextMenu)

        # 로그 출력 영역
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)

        # 로깅 관련 객체 생성 및 설정
        self.log_emitter = LogSignalEmitter(self) # 시그널 발생기 (부모 지정 가능)
        self.log_handler = QTextEditHandler(self.log_emitter) # 핸들러에 발생기 전달
        logging.getLogger().addHandler(self.log_handler)
        self.log_handler.setLevel(logging.INFO)

    def _setup_layout(self):
        """UI 위젯들을 레이아웃에 배치."""
        # URL 입력 레이아웃
        self.url_layout = QHBoxLayout()
        self.url_layout.addWidget(self.url_input)
        self.url_layout.addWidget(self.paste_btn)

        # 설정 버튼 레이아웃
        self.settings_layout = QHBoxLayout()
        self.settings_layout.addWidget(self.login_status_label)
        self.settings_layout.addWidget(self.login_btn)
        self.settings_layout.addWidget(self.logout_btn)
        self.settings_layout.addWidget(self.open_config_btn)

        # 메인 수직 레이아웃
        self.layout = QVBoxLayout()
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

        # 메인 위젯에 레이아웃 설정 및 중앙 위젯으로 등록
        self.main_widget.setLayout(self.layout)
        self.setCentralWidget(self.main_widget)

    def _connect_signals(self):
        """UI 위젯 시그널과 슬롯 연결."""
        # 버튼 클릭
        self.paste_btn.clicked.connect(self.paste_from_clipboard)
        self.download_btn.clicked.connect(self.start_extraction)
        self.login_btn.clicked.connect(self.show_login_window)
        self.logout_btn.clicked.connect(self.logout)
        self.open_config_btn.clicked.connect(self.open_config_folder)
        self.save_path_btn.clicked.connect(self.choose_save_path)

        # Task Manager 시그널
        self.task_manager.task_progress.connect(self.update_task_progress)
        self.task_manager.task_finished.connect(self.handle_task_finished)
        self.task_manager.task_added.connect(self.add_task_to_list)

        # 다운로드 목록 컨텍스트 메뉴
        self.task_list_widget.customContextMenuRequested.connect(
            self.show_task_context_menu
        )

        # 로그 시그널 발생기의 시그널을 QTextEdit 슬롯에 연결
        self.log_emitter.log_received.connect(self.log_output.append)

    def _load_initial_settings(self):
        """애플리케이션 시작 시 필요한 초기 설정 로드 및 적용."""
        # 저장 경로 초기화
        self.save_path = os.getcwd()  # 기본값 먼저 설정
        try:
            loaded_save_path = self.config_manager.load_setting("save_path")
            if loaded_save_path and os.path.isdir(loaded_save_path):
                self.save_path = loaded_save_path
                logging.info(f"저장 경로 로드 성공: {self.save_path}")
            elif loaded_save_path:
                # 설정 파일에 경로가 있지만 유효하지 않은 경우
                logging.warning(
                    f"설정된 저장 경로({loaded_save_path})가 유효하지 않아 기본 경로({self.save_path})를 사용합니다."
                )
                # 필요하다면 사용자에게 알림 또는 잘못된 설정 초기화
                # self.config_manager.save_setting('save_path', self.save_path)
            # else: 설정 파일에 save_path 자체가 없는 경우 - 기본값 사용 (별도 로깅 불필요)
        except Exception as e:
            # 설정 파일 자체를 읽는 데 문제가 있는 경우
            logging.exception(f"저장 경로 로드 중 오류 발생: {e}")
        self.save_path_display.setText(self.save_path)

        # 로그인 상태 초기화 (쿠키 로드 시도)
        self.load_and_prepare_cookies()

    # --- 기존 슬롯 및 메서드들 --- (아래로 이동)

    def save_current_settings(self):
        """앱 종료 시 현재 설정을 저장."""
        if hasattr(self, "save_path") and self.save_path:
            logging.info(f"앱 종료, 현재 저장 경로 저장: {self.save_path}")
            if hasattr(self, "config_manager"):
                if not self.config_manager.save_setting("save_path", self.save_path):
                    logging.error("앱 종료 중 저장 경로 저장 실패.")
            else:
                logging.warning("앱 종료 중 config_manager에 접근할 수 없습니다.")
        else:
            logging.info("앱 종료 중 save_path 속성을 찾을 수 없거나 비어 있습니다.")

    def load_and_prepare_cookies(self):
        """저장된 쿠키를 로드하고 임시 파일로 준비."""
        logging.info("저장된 쿠키 로드 시도...")
        self.temp_cookie_file_path = None
        try:
            netscape_cookie_string = self.config_manager.load_cookies()
            if netscape_cookie_string:
                self.cleanup_temp_files()
                temp_cookie_file = tempfile.NamedTemporaryFile(
                    mode="w", suffix=".txt", delete=False, encoding="utf-8"
                )
                temp_cookie_file.write(netscape_cookie_string)
                temp_cookie_file.close()
                self.temp_cookie_file_path = temp_cookie_file.name
                logging.info(f"임시 쿠키 파일 생성 완료: {self.temp_cookie_file_path}")
                self.update_login_status(logged_in=True)
            else:
                logging.info("로드할 유효한 쿠키 없음.")
                self.update_login_status(logged_in=False)
        except Exception as e:
            logging.exception("쿠키 로드/준비 중 예상치 못한 오류 발생")
            self.update_login_status(logged_in=False)
            self.cleanup_temp_files()

    def cleanup_temp_files(self):
        """앱 종료 시 임시 쿠키 파일 정리."""
        if self.temp_cookie_file_path and os.path.exists(self.temp_cookie_file_path):
            try:
                os.remove(self.temp_cookie_file_path)
                logging.info(f"임시 쿠키 파일 삭제: {self.temp_cookie_file_path}")
            except (IOError, OSError) as e:
                logging.error(f"임시 쿠키 파일 삭제 오류: {e}")
            finally:
                self.temp_cookie_file_path = None

    def update_login_status(self, logged_in):
        """로그인 상태에 따라 UI 업데이트."""
        if logged_in:
            self.login_status_label.setText("로그인됨")
            self.login_btn.setText("다시 로그인")
            self.logout_btn.setVisible(True)
        else:
            self.login_status_label.setText("로그아웃 상태")
            self.login_btn.setText("YouTube 로그인")
            self.logout_btn.setVisible(False)
            self.cleanup_temp_files()

    def choose_save_path(self):
        """폴더 선택 대화상자를 열어 저장 경로를 선택."""
        start_dir = self.save_path if os.path.isdir(self.save_path) else os.getcwd()
        folder = QFileDialog.getExistingDirectory(
            self, "Select Save Directory", dir=start_dir
        )
        if folder:
            self.save_path = folder
            self.save_path_display.setText(folder)

    @Slot()
    def start_extraction(self):
        """입력된 URL에 대한 정보 추출 및 다운로드 작업 시작."""
        video_url = self.url_input.text()
        if not video_url:
            logging.warning("추출 시작 실패: YouTube 비디오 URL을 입력하세요.")
            QMessageBox.warning(self, "URL 필요", "YouTube 비디오 URL을 입력해주세요.")
            return
        if not self.save_path:
            logging.warning("추출 시작 실패: 저장 디렉토리를 선택하세요.")
            QMessageBox.warning(
                self, "저장 폴더 필요", "다운로드할 폴더를 선택해주세요."
            )
            return
        logging.info(f"Requesting extraction for URL: {video_url}")
        self.task_manager.start_new_task(
            video_url, self.save_path, self.temp_cookie_file_path
        )

    @Slot(str, int, int)
    def update_task_progress(self, task_id, value, max_value):
        """Task Manager로부터 받은 진행률 정보로 목록 아이템 업데이트."""
        for i in range(self.task_list_widget.count()):
            item = self.task_list_widget.item(i)
            if item.data(Qt.UserRole) == task_id:
                if max_value > 0:
                    item.setText(f"{task_id} - {value}% ({value}/{max_value})")
                else:
                    item.setText(f"{task_id} - Processing...")
                return
        logging.warning(f"Progress update received for item not in list: {task_id}")

    @Slot(str, bool)
    def handle_task_finished(self, task_id, success):
        """Task Manager로부터 받은 작업 완료 정보로 목록 아이템 상태 업데이트."""
        logging.info(f"Handling finished task in UI: {task_id}, Success: {success}")
        for i in range(self.task_list_widget.count()):
            item = self.task_list_widget.item(i)
            if item.data(Qt.UserRole) == task_id:
                if task_id.startswith("Extracting_") and success:
                    self.task_list_widget.takeItem(i)
                    logging.debug(
                        f"Removed temporary extraction task item from list: {task_id}"
                    )
                else:
                    status = "Completed" if success else "Failed/Cancelled"
                    item.setText(f"{task_id} - {status}")
                    if not success:
                        item.setForeground(Qt.red)
                return
        logging.warning(f"Finished signal received for item not in list: {task_id}")

    def paste_from_clipboard(self):
        """클립보드의 텍스트를 URL 입력창에 붙여넣기."""
        clipboard = QApplication.clipboard()
        self.url_input.setText(clipboard.text())

    def show_login_window(self):
        """YouTube 로그인 창을 표시하거나 이미 열려있으면 활성화."""
        logging.info("로그인 창 표시 요청")
        if self.auth_window and self.auth_window.isVisible():
            logging.info("로그인 창이 이미 열려 있음. 활성화.")
            self.auth_window.activateWindow()
            self.auth_window.raise_()
            return
        try:
            logging.info("YouTubeAuthWindow 인스턴스 생성 시도...")
            # YouTubeAuthWindow 생성 시 config_manager 전달 확인
            self.auth_window = YouTubeAuthWindow(config_manager=self.config_manager)
            self.auth_window.login_completed.connect(self.handle_login_completed)
            logging.info("YouTubeAuthWindow 생성 및 시그널 연결 완료.")
            self.auth_window.show()
        except Exception as e:
            logging.exception("YouTubeAuthWindow 생성 중 오류")
            QMessageBox.critical(
                self,
                "로그인 오류",
                f"로그인 창을 생성하는 중 오류가 발생했습니다:\n{e}",
            )
            self.auth_window = None

    @Slot()
    def handle_login_completed(self):
        """로그인이 완료되면 쿠키를 다시 로드하고 상태 업데이트."""
        logging.info("[App] 로그인 완료 처리 시작.")
        self.load_and_prepare_cookies()

    @Slot()
    def logout(self):
        """로그아웃 처리: 저장된 쿠키 삭제 및 상태 업데이트."""
        logging.info("로그아웃 요청")
        if self.config_manager.delete_cookies():
            logging.info("저장된 쿠키 삭제 완료.")
        else:
            logging.error("쿠키 삭제 중 오류 발생.")
        self.update_login_status(logged_in=False)
        logging.info("로그아웃 처리 완료.")

    def open_config_folder(self):
        """설정 폴더(애플리케이션 데이터 폴더)를 파일 탐색기로 엽니다."""
        config_path = self.config_manager.app_dir
        logging.info(f"설정 폴더 열기 요청: {config_path}")
        try:
            os.makedirs(config_path, exist_ok=True)
            if os.name == "nt":
                os.startfile(config_path)
            elif os.name == "posix":
                if sys.platform == "darwin":
                    subprocess.run(["open", config_path])
                else:
                    subprocess.run(["xdg-open", config_path])
            logging.info(f"설정 폴더 열기 시도: {config_path}")
        except Exception as e:
            logging.exception("설정 폴더 열기 오류")
            QMessageBox.warning(
                self, "폴더 열기 오류", f"설정 폴더를 여는 중 오류가 발생했습니다: {e}"
            )

    def show_task_context_menu(self, position):
        """다운로드 목록 항목에서 우클릭 시 컨텍스트 메뉴 표시."""
        item = self.task_list_widget.itemAt(position)
        if item:
            task_id = item.data(Qt.UserRole)
            if task_id:
                menu = QMenu()
                cancel_action = menu.addAction("Cancel Task")
                action = menu.exec(self.task_list_widget.mapToGlobal(position))
                if action == cancel_action:
                    logging.info(
                        f"Requesting cancellation for task via context menu: {task_id}"
                    )
                    self.task_manager.cancel_task(task_id)
                    item.setText(f"{task_id} - Cancelling...")
                    item.setForeground(Qt.yellow)

    @Slot(str, str)
    def add_task_to_list(self, task_id, initial_status_text):
        """Task Manager로부터 받은 새 작업 정보를 목록에 추가하거나 상태 업데이트."""
        items = self.task_list_widget.findItems(
            task_id, Qt.MatchExactly | Qt.MatchCaseSensitive
        )
        if not items:
            item = QListWidgetItem(initial_status_text)
            item.setData(Qt.UserRole, task_id)
            self.task_list_widget.addItem(item)
            logging.info(f"Task added to list: {task_id}")
        else:
            items[0].setText(initial_status_text)
            logging.info(f"Task status updated in list: {task_id}")


if __name__ == "__main__":
    setup_logging()
    app = QApplication(sys.argv)
    try:
        window = VideoDownloaderApp()
        window.show()
        sys.exit(app.exec())
    except SystemExit:
        pass
    except Exception as e:
        logging.critical(f"Application initialization failed: {e}", exc_info=True)
        print(f"CRITICAL ERROR: Application failed to initialize - {e}")
        sys.exit(1)
