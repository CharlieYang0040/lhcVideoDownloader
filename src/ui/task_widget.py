import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QProgressBar, QPushButton, QDialog, QTextEdit, QSizePolicy, QApplication
)
from PySide6.QtCore import Qt, Slot, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from src.core.downloader import VideoDownloader, DownloaderThread
from src.ui.theme import APP_STYLESHEET, refresh_style
from src.utils.helpers import get_logs_dir


class LogDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("작업 로그")
        self.resize(600, 400)
        self.setStyleSheet(APP_STYLESHEET)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        layout.addWidget(self.text_edit)

        controls_layout = QHBoxLayout()
        self.open_logs_dir_btn = QPushButton("로그 폴더 열기")
        self.open_logs_dir_btn.setObjectName("SecondaryButton")
        self.open_logs_dir_btn.clicked.connect(self.open_logs_dir)
        controls_layout.addWidget(self.open_logs_dir_btn)
        controls_layout.addStretch()
        self.copy_btn = QPushButton("복사")
        self.copy_btn.setObjectName("SecondaryButton")
        self.copy_btn.clicked.connect(self.copy_logs)
        close_btn = QPushButton("닫기")
        close_btn.setObjectName("SecondaryButton")
        close_btn.clicked.connect(self.close)
        controls_layout.addWidget(self.copy_btn)
        controls_layout.addWidget(close_btn)
        layout.addLayout(controls_layout)

    def append_log(self, text):
        self.text_edit.append(text)

    def copy_logs(self):
        QApplication.clipboard().setText(self.text_edit.toPlainText())

    def open_logs_dir(self):
        logs_dir = get_logs_dir()
        os.makedirs(logs_dir, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(logs_dir))


class TaskWidget(QWidget):
    removed = Signal(QWidget)  # Signal to remove self from parent list
    login_retry_requested = Signal(QWidget)

    def __init__(self, url, path, audio_only, cookies, codec, preset, target_ext, overwrite, threads, fragments, fallback_cookies=None):
        super().__init__()
        self.url = url
        self._cancelled = False
        self._auth_failed = False
        self.setObjectName("TaskRow")

        # Layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        # Header: Title + Status
        header_layout = QHBoxLayout()
        self.title_label = QLabel(f"URL: {url}")
        self.title_label.setObjectName("TaskTitle")
        self.title_label.setWordWrap(False)
        self.title_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.title_label.setMinimumWidth(0)

        self.status_label = QLabel()
        self.status_label.setObjectName("StatusBadge")
        self.status_label.setFixedWidth(112)
        self.status_label.setAlignment(Qt.AlignCenter)
        self.set_status("대기", "idle")

        header_layout.addWidget(self.title_label, stretch=1)
        header_layout.addWidget(self.status_label, stretch=0)
        layout.addLayout(header_layout)

        # Details
        display_ext = target_ext.upper() if target_ext else "AUTO"
        detail_text = f"포맷: {display_ext} | 코덱: {codec} | 옵션: {preset}"
        if audio_only:
            detail_text += " (오디오 전용)"
        if overwrite:
            detail_text += " | 덮어쓰기: ON"

        self.detail_label = QLabel(detail_text)
        self.detail_label.setObjectName("MutedLabel")
        layout.addWidget(self.detail_label)

        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)

        # Metrics & Controls
        controls_layout = QHBoxLayout()
        self.metrics_label = QLabel("속도: - | 남은 시간: -")
        self.metrics_label.setObjectName("MetricsLabel")

        self.retry_auth_btn = QPushButton("로그인 후 재시도")
        self.retry_auth_btn.setObjectName("QueueButton")
        self.retry_auth_btn.setMinimumHeight(22)
        self.retry_auth_btn.setMaximumHeight(24)
        self.retry_auth_btn.setCursor(Qt.PointingHandCursor)
        self.retry_auth_btn.setToolTip("YouTube에 로그인하고 이 작업을 다시 시도합니다.")
        self.retry_auth_btn.clicked.connect(lambda: self.login_retry_requested.emit(self))
        self.retry_auth_btn.hide()

        self.log_btn = QPushButton("로그")
        self.log_btn.setObjectName("QueueButton")
        self.log_btn.setMinimumSize(50, 22)
        self.log_btn.setMaximumHeight(24)
        self.log_btn.setCursor(Qt.PointingHandCursor)
        self.log_btn.setToolTip("상세 로그를 확인합니다.")
        self.log_btn.clicked.connect(self.show_logs)

        self.cancel_btn = QPushButton("취소")
        self.cancel_btn.setObjectName("QueueDangerButton")
        self.cancel_btn.setMinimumSize(50, 22)
        self.cancel_btn.setMaximumHeight(24)
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.setToolTip("작업을 취소합니다.")
        self.cancel_btn.clicked.connect(self.cancel_download)

        controls_layout.addWidget(self.metrics_label, stretch=1)
        controls_layout.addWidget(self.retry_auth_btn)
        controls_layout.addWidget(self.log_btn)
        controls_layout.addWidget(self.cancel_btn)
        layout.addLayout(controls_layout)

        # Logic
        self.downloader = VideoDownloader(
            url,
            path,
            audio_only,
            cookies,
            codec,
            preset,
            target_ext,
            overwrite,
            threads,
            fragments,
            fallback_cookies=fallback_cookies,
        )
        self.thread = DownloaderThread(self.downloader)

        self.downloader.progress_update.connect(self.on_progress)
        self.downloader.log_message.connect(self.on_log)
        self.downloader.status_update.connect(self.on_status)
        self.downloader.finished.connect(self.on_finished)
        self.downloader.error_occurred.connect(self.on_error)
        self.downloader.auth_required.connect(self.on_auth_required)

        self.log_dialog = LogDialog(self)
        self.logs = []  # Keep logs in memory

    def start(self):
        self._cancelled = False
        self._auth_failed = False
        self.retry_auth_btn.hide()
        self.set_status("진행 중", "running")
        self.thread.start()

    def set_status(self, text, state="idle"):
        self.status_label.setText(text)
        self.status_label.setProperty("state", state)
        refresh_style(self.status_label)

    def set_removable_state(self):
        self.cancel_btn.setText("삭제")
        self.cancel_btn.setObjectName("QueueButton")
        refresh_style(self.cancel_btn)
        self.cancel_btn.setToolTip("목록에서 제거합니다.")

    def retry_with_cookies(self, cookies):
        if self.thread.isRunning():
            self.thread.wait(3000)
        self.cancel_btn.setText("취소")
        self.cancel_btn.setObjectName("QueueDangerButton")
        refresh_style(self.cancel_btn)
        self.cancel_btn.setToolTip("작업을 취소합니다.")
        self.progress_bar.setValue(0)
        self.metrics_label.setText("속도: - | 남은 시간: -")
        self.downloader.set_cookies(cookies, cookies)
        self.start()

    def is_active(self):
        return self.downloader.is_running or self.thread.isRunning()

    def stop_for_shutdown(self):
        self._cancelled = True
        if self.downloader.is_running:
            self.downloader.stop()
        if self.thread.isRunning():
            self.thread.wait(3000)

    @Slot(float, str, str)
    def on_progress(self, percent, speed, eta):
        if self._cancelled:
            return
        self.progress_bar.setValue(int(percent))
        self.metrics_label.setText(f"속도: {speed} | 남은 시간: {eta}")

    @Slot(str)
    def on_status(self, status):
        if self._cancelled:
            return
        self.set_status(status, "running")

    @Slot(str)
    def on_log(self, msg):
        self.logs.append(msg)
        if self.log_dialog.isVisible():
            self.log_dialog.append_log(msg)

    @Slot()
    def show_logs(self):
        self.log_dialog.text_edit.setPlainText("\n".join(self.logs))
        self.log_dialog.show()

    @Slot()
    def cancel_download(self):
        if self.downloader.is_running:
            self._cancelled = True
            self.downloader.stop()
            self.set_status("취소됨", "warning")
            self.set_removable_state()
        else:
            # If already finished/stopped, remove widget
            self.removed.emit(self)

    @Slot()
    def on_finished(self):
        if self._cancelled:
            return
        self.set_status("완료", "done")
        self.progress_bar.setValue(100)
        self.set_removable_state()

    @Slot(str)
    def on_auth_required(self, msg):
        if self._cancelled:
            return
        self._auth_failed = True
        self.set_status("인증 필요", "warning")
        self.on_log(f"AUTH REQUIRED: {msg}")
        self.retry_auth_btn.show()
        self.set_removable_state()

    @Slot(str)
    def on_error(self, err):
        if self._cancelled or self._auth_failed:
            return
        self.set_status("오류", "error")
        self.on_log(f"ERROR: {err}")
        self.set_removable_state()
