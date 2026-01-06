from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QProgressBar, QPushButton, QMessageBox, QDialog, QTextEdit, QSizePolicy
)
from PySide6.QtCore import Qt, Slot, Signal
from src.core.downloader import VideoDownloader, DownloaderThread

class LogDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("작업 로그 (Task Logs)")
        self.resize(600, 400)
        layout = QVBoxLayout(self)
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        layout.addWidget(self.text_edit)

    def append_log(self, text):
        self.text_edit.append(text)

class TaskWidget(QWidget):
    removed = Signal(QWidget) # Signal to remove self from parent list

    def __init__(self, url, path, audio_only, cookies, codec, preset, target_ext, overwrite, threads, fragments):
        super().__init__()
        self.url = url
        
        # Layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        
        # Card Style
        self.setStyleSheet("""
            TaskWidget {
                background-color: #333333; 
                border-radius: 10px;
                border: 1px solid #444;
            }
            QLabel { color: #f0f0f0; }
        """)

        # Header: Title + Status
        header_layout = QHBoxLayout()
        self.title_label = QLabel(f"URL: {url}")
        self.title_label.setStyleSheet("font-weight: bold; font-size: 13px; color: #ffffff;")
        self.title_label.setWordWrap(False)
        self.title_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.title_label.setMinimumWidth(0)

        self.status_label = QLabel("대기 중...")
        self.status_label.setStyleSheet("color: #aaaaaa; font-weight: bold;")
        self.status_label.setFixedWidth(100) 
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        
        header_layout.addWidget(self.title_label, stretch=1)
        header_layout.addWidget(self.status_label, stretch=0)
        layout.addLayout(header_layout)

        # Details
        display_ext = target_ext.upper() if target_ext else "AUTO"
        detail_text = f"포맷: {display_ext} | 코덱: {codec} | 옵션: {preset}"
        if audio_only: detail_text += " (오디오 전용)"
        if overwrite: detail_text += " | 덮어쓰기: ON"

        self.detail_label = QLabel(detail_text)
        self.detail_label.setStyleSheet("color: #888888; font-size: 11px; margin-bottom: 5px;")
        layout.addWidget(self.detail_label)

        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: none;
                background-color: #444;
                border-radius: 5px;
                height: 8px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #4caf50;
                border-radius: 5px;
            }
        """)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)

        # Metrics & Controls
        controls_layout = QHBoxLayout()
        self.metrics_label = QLabel("속도: - | 남은 시간: -")
        self.metrics_label.setStyleSheet("color: #bbbbbb; font-size: 11px;")
        
        # Fix Button Clipping: Remove strict fixed height or increase it
        # Min height is better
        
        self.log_btn = QPushButton("로그")
        self.log_btn.setMinimumSize(60, 28) # Increased height
        self.log_btn.setCursor(Qt.PointingHandCursor)
        self.log_btn.setStyleSheet("background-color: #555; color: white; border-radius: 4px; padding: 0px;")
        self.log_btn.setToolTip("상세 로그를 확인합니다.")
        self.log_btn.clicked.connect(self.show_logs)
        
        self.cancel_btn = QPushButton("취소")
        self.cancel_btn.setMinimumSize(60, 28) # Increased height
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.setStyleSheet("""
            QPushButton { background-color: #d32f2f; color: white; border-radius: 4px; padding: 0px; }
            QPushButton:hover { background-color: #b71c1c; }
        """)
        self.cancel_btn.setToolTip("작업을 취소합니다.")
        self.cancel_btn.clicked.connect(self.cancel_download)

        controls_layout.addWidget(self.metrics_label, stretch=1)
        controls_layout.addWidget(self.log_btn)
        controls_layout.addWidget(self.cancel_btn)
        layout.addLayout(controls_layout)

        # Logic
        self.downloader = VideoDownloader(url, path, audio_only, cookies, codec, preset, target_ext, overwrite, threads, fragments)
        self.thread = DownloaderThread(self.downloader)
        
        self.downloader.progress_update.connect(self.on_progress)
        self.downloader.log_message.connect(self.on_log)
        self.downloader.finished.connect(self.on_finished)
        self.downloader.error_occurred.connect(self.on_error)
        
        self.log_dialog = LogDialog(self)
        self.logs = [] # Keep logs in memory

    def start(self):
        self.status_label.setText("진행 중")
        self.status_label.setStyleSheet("color: #4caf50;")
        self.thread.start()

    @Slot(float, str, str)
    def on_progress(self, percent, speed, eta):
        self.progress_bar.setValue(int(percent))
        self.metrics_label.setText(f"속도: {speed} | 남은 시간: {eta}")

    @Slot(str)
    def on_log(self, msg):
        self.logs.append(msg)
        if self.log_dialog.isVisible():
            self.log_dialog.append_log(msg)
        
        # Try to parse title if not set
        if "Destination: " in msg and "URL: " in self.title_label.text():
            # Rough heuristic
            pass

    @Slot()
    def show_logs(self):
        self.log_dialog.text_edit.setPlainText("\n".join(self.logs))
        self.log_dialog.show()

    @Slot()
    def cancel_download(self):
        if self.downloader.is_running:
            self.downloader.stop()
            self.status_label.setText("취소됨")
            self.status_label.setStyleSheet("color: #e6a23c;")
            self.thread.quit()
        else:
            # If already finished/stopped, remove widget
            self.removed.emit(self)

    @Slot()
    def on_finished(self):
        self.status_label.setText("완료")
        self.status_label.setStyleSheet("color: #4caf50;")
        self.progress_bar.setValue(100)
        self.thread.quit()
        self.cancel_btn.setText("삭제") # Change cancel to remove
        self.cancel_btn.setToolTip("목록에서 제거합니다.")

    @Slot(str)
    def on_error(self, err):
        self.status_label.setText("오류")
        self.status_label.setStyleSheet("color: #f56c6c;")
        self.on_log(f"ERROR: {err}")
        self.thread.quit()
