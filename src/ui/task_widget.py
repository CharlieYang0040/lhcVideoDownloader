from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QProgressBar, QPushButton, QMessageBox, QDialog, QTextEdit, QSizePolicy
)
from PySide6.QtCore import Qt, Slot, Signal
from src.core.downloader import VideoDownloader, DownloaderThread

class LogDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Task Logs")
        self.resize(600, 400)
        layout = QVBoxLayout(self)
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        layout.addWidget(self.text_edit)

    def append_log(self, text):
        self.text_edit.append(text)

class TaskWidget(QWidget):
    removed = Signal(QWidget) # Signal to remove self from parent list

    def __init__(self, url, path, audio_only, cookies, post_process):
        super().__init__()
        self.url = url
        
        # Layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        self.setStyleSheet("background-color: #2b2b2b; border-radius: 5px;")

        # Header: Title + Status
        header_layout = QHBoxLayout()
        self.title_label = QLabel(f"URL: {url}")
        self.title_label.setStyleSheet("font-weight: bold; color: #ffffff;")
        # Fix overflow: Elide text from the middle if too long
        self.title_label.setWordWrap(False)
        self.title_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        
        # We need to make the label shrinkable so it doesn't push the layout
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        
        # Note: Standard QLabel elision often requires a custom paintEvent or setting text with metrics.
        # Simpler approach for now: set a strict maximum width or use a style that allows shrinking.
        # But QBoxLayout usually handles this if we set stretch correctly.
        # Let's try adding `setMinimumWidth(0)` and ensure stretch is set.
        self.title_label.setMinimumWidth(0)

        self.status_label = QLabel("Waiting...")
        self.status_label.setStyleSheet("color: #aaaaaa;")
        self.status_label.setFixedWidth(80) # Fixed width for status to prevent jumping
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        
        header_layout.addWidget(self.title_label, stretch=1)
        header_layout.addWidget(self.status_label, stretch=0)
        layout.addLayout(header_layout)

        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet("QProgressBar { height: 10px; }")
        layout.addWidget(self.progress_bar)

        # Metrics & Controls
        controls_layout = QHBoxLayout()
        self.metrics_label = QLabel("Speed: - | ETA: -")
        self.metrics_label.setStyleSheet("color: #cccccc;")
        
        self.log_btn = QPushButton("Logs")
        self.log_btn.setFixedSize(60, 25)
        self.log_btn.clicked.connect(self.show_logs)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setFixedSize(60, 25)
        self.cancel_btn.setStyleSheet("background-color: #c94c4c; color: white;")
        self.cancel_btn.clicked.connect(self.cancel_download)

        controls_layout.addWidget(self.metrics_label, stretch=1)
        controls_layout.addWidget(self.log_btn)
        controls_layout.addWidget(self.cancel_btn)
        layout.addLayout(controls_layout)

        # Logic
        self.downloader = VideoDownloader(url, path, audio_only, cookies, post_process)
        self.thread = DownloaderThread(self.downloader)
        
        self.downloader.progress_update.connect(self.on_progress)
        self.downloader.log_message.connect(self.on_log)
        self.downloader.finished.connect(self.on_finished)
        self.downloader.error_occurred.connect(self.on_error)
        
        self.log_dialog = LogDialog(self)
        self.logs = [] # Keep logs in memory

    def start(self):
        self.status_label.setText("Running")
        self.status_label.setStyleSheet("color: #4caf50;")
        self.thread.start()

    @Slot(float, str, str)
    def on_progress(self, percent, speed, eta):
        self.progress_bar.setValue(int(percent))
        self.metrics_label.setText(f"Speed: {speed} | ETA: {eta}")

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
            self.status_label.setText("Cancelled")
            self.status_label.setStyleSheet("color: #e6a23c;")
            self.thread.quit()
        else:
            # If already finished/stopped, remove widget
            self.removed.emit(self)

    @Slot()
    def on_finished(self):
        self.status_label.setText("Completed")
        self.status_label.setStyleSheet("color: #4caf50;")
        self.progress_bar.setValue(100)
        self.thread.quit()
        self.cancel_btn.setText("Remove") # Change cancel to remove

    @Slot(str)
    def on_error(self, err):
        self.status_label.setText("Error")
        self.status_label.setStyleSheet("color: #f56c6c;")
        self.on_log(f"ERROR: {err}")
        self.thread.quit()
