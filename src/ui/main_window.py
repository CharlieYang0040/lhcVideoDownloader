import os
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox,
    QFileDialog, QListWidget, QListWidgetItem, QMessageBox, QApplication
)
from PySide6.QtCore import Qt, Slot
from src.ui.task_widget import TaskWidget

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LHC Video Downloader (Enhanced)")
        self.setMinimumSize(800, 600)
        
        # Central Widget & Layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)

        # 1. Input Area
        input_group = QWidget()
        input_layout = QHBoxLayout(input_group)
        input_layout.setContentsMargins(0, 0, 0, 0)
        
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Paste YouTube/Vimeo link here...")
        
        self.paste_btn = QPushButton("Paste")
        self.paste_btn.setFixedWidth(60)
        self.paste_btn.clicked.connect(self.paste_url)
        
        self.add_btn = QPushButton("Add Task")
        self.add_btn.setStyleSheet("background-color: #409eff; color: white; font-weight: bold;")
        self.add_btn.clicked.connect(self.add_task)

        input_layout.addWidget(QLabel("URL:"))
        input_layout.addWidget(self.url_input)
        input_layout.addWidget(self.paste_btn)
        input_layout.addWidget(self.add_btn)
        
        main_layout.addWidget(input_group)

        # 2. Options Area
        opts_group = QWidget()
        opts_layout = QHBoxLayout(opts_group)
        opts_layout.setContentsMargins(0, 0, 0, 0)

        # Path
        self.path_input = QLineEdit()
        self.path_input.setText(os.path.join(os.getcwd(), 'downloads'))
        self.browse_btn = QPushButton("...")
        self.browse_btn.setFixedWidth(40)
        self.browse_btn.clicked.connect(self.browse_folder)

        # Format
        self.format_combo = QComboBox()
        self.format_combo.addItems(["Best Video + Audio (MP4)", "Audio Only (MP3)"])
        
        # Auth
        self.auth_type_combo = QComboBox()
        self.auth_type_combo.addItems(["Browser", "File"])
        self.auth_type_combo.currentIndexChanged.connect(self.toggle_auth_input)
        
        self.auth_input = QWidget()
        self.auth_input_layout = QHBoxLayout(self.auth_input)
        self.auth_input_layout.setContentsMargins(0, 0, 0, 0)
        
        # Browser Selection
        self.browser_combo = QComboBox()
        self.browser_combo.addItems(["None", "chrome", "firefox", "edge", "whale"])
        
        # File Selection
        self.cookie_file_edit = QLineEdit()
        self.cookie_file_edit.setPlaceholderText("Select cookies.txt...")
        self.cookie_file_btn = QPushButton("...")
        self.cookie_file_btn.setFixedWidth(30)
        self.cookie_file_btn.clicked.connect(self.browse_cookie_file)
        
        # Initially show browser combo
        self.auth_input_layout.addWidget(self.browser_combo)
        
        # Post Process
        self.post_combo = QComboBox()
        self.post_combo.addItems(["None", "H264 (CPU)", "NVENC H264"])
        self.post_combo.setToolTip("Re-encode video after download")

        opts_layout.addWidget(QLabel("Save to:"))
        opts_layout.addWidget(self.path_input)
        opts_layout.addWidget(self.browse_btn)
        opts_layout.addWidget(QLabel("Format:"))
        opts_layout.addWidget(self.format_combo)
        opts_layout.addWidget(QLabel("Cookies:"))
        opts_layout.addWidget(self.auth_type_combo)
        opts_layout.addWidget(self.auth_input)
        opts_layout.addWidget(QLabel("Encoding:"))
        opts_layout.addWidget(self.post_combo)

        main_layout.addWidget(opts_group)

        # 3. Task List
        self.task_list = QListWidget()
        self.task_list.setStyleSheet("background-color: #1e1e1e;")
        main_layout.addWidget(self.task_list)

    @Slot()
    def toggle_auth_input(self):
        # Clear layout
        while self.auth_input_layout.count():
            item = self.auth_input_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
        
        if self.auth_type_combo.currentText() == "Browser":
            self.auth_input_layout.addWidget(self.browser_combo)
        else:
            self.auth_input_layout.addWidget(self.cookie_file_edit)
            self.auth_input_layout.addWidget(self.cookie_file_btn)

    @Slot()
    def browse_cookie_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Cookies File", "", "Text Files (*.txt);;All Files (*)")
        if file_path:
            self.cookie_file_edit.setText(file_path)

    @Slot()
    def paste_url(self):
        clipboard = QApplication.clipboard()
        self.url_input.setText(clipboard.text())

    @Slot()
    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Download Folder")
        if folder:
            self.path_input.setText(folder)

    @Slot()
    def add_task(self):
        url = self.url_input.text().strip()
        path = self.path_input.text().strip()
        
        if not url:
            QMessageBox.warning(self, "Input Error", "Please enter a URL.")
            return

        if not os.path.exists(path):
            try:
                os.makedirs(path)
            except OSError:
                QMessageBox.warning(self, "Path Error", "Invalid download path.")
                return

        # Get Options
        audio_only = self.format_combo.currentIndex() == 1
        
        # Auth Logic
        cookies = None
        if self.auth_type_combo.currentText() == "Browser":
            browser = self.browser_combo.currentText()
            if browser != "None":
                cookies = f"browser:{browser}" # Custom format to pass to downloader
        else:
            cookie_file = self.cookie_file_edit.text().strip()
            if cookie_file:
                 cookies = f"file:{cookie_file}"

        post_process = self.post_combo.currentText()

        # Create Task Widget
        task_widget = TaskWidget(url, path, audio_only, cookies, post_process)
        task_widget.removed.connect(self.remove_task)
        
        # Add to List
        item = QListWidgetItem(self.task_list)
        item.setSizeHint(task_widget.sizeHint())
        
        self.task_list.addItem(item)
        self.task_list.setItemWidget(item, task_widget)
        
        # Start
        task_widget.start()
        
        # Clear Input
        self.url_input.clear()

    @Slot(QWidget)
    def remove_task(self, widget):
        for i in range(self.task_list.count()):
            item = self.task_list.item(i)
            if self.task_list.itemWidget(item) == widget:
                self.task_list.takeItem(i)
                break
