import os
import logging
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                               QPushButton, QLineEdit, QListWidget, QListWidgetItem,
                               QComboBox, QLabel, QFileDialog, QGroupBox, QMessageBox, QToolTip, QApplication, QCheckBox, QSpinBox)
from PySide6.QtCore import Slot, QSize, QUrl
from PySide6.QtGui import QDesktopServices
from src.ui.task_widget import TaskWidget
from src.ui.login_dialog import LoginDialog
from src.utils.config import ConfigManager

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.debug("Initializing MainWindow...")
        self.setWindowTitle("LHC Video Downloader")
        self.resize(1000, 720)
        
        # Load Config
        self.config = ConfigManager()
        
        # Style
        self.setStyleSheet("""
            QMainWindow { background-color: #2b2b2b; color: #ffffff; }
            QLabel { color: #cccccc; font-weight: bold; font-size: 14px; }
            QLineEdit, QComboBox { 
                padding: 8px; border-radius: 5px; border: 1px solid #555; 
                background-color: #333; color: white; selection-background-color: #555;
            }
            QComboBox::drop-down { border: none; }
            QComboBox::down-arrow { image: none; border-left: 1px solid #555; }
            QPushButton {
                background-color: #3f51b5; color: white;
                border: none; padding: 8px 16px; border-radius: 5px;
                font-weight: bold; font-size: 13px;
            }
            QPushButton:hover { background-color: #5c6bc0; }
            QPushButton#ActionBtn { background-color: #2e7d32; }
            QPushButton#ActionBtn:hover { background-color: #388e3c; }
            QPushButton#SmallBtn { padding: 5px; background-color: #616161; }
            QPushButton#SmallBtn:hover { background-color: #757575; }
            QGroupBox { 
                border: 1px solid #444; border-radius: 5px; 
                margin-top: 20px; font-weight: bold; color: #eee;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
            QListWidget { border: 1px solid #444; border-radius: 5px; background-color: #1e1e1e; }
        """)

        # Main Layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(25, 25, 25, 25)

        # 1. Input Area
        input_group = QGroupBox("새로운 다운로드 추가 (Add New Download)")
        input_layout = QHBoxLayout(input_group)
        input_layout.setSpacing(10)
        
        # URL History Combo
        self.url_combo = QComboBox()
        self.url_combo.setEditable(True)
        self.url_combo.setPlaceholderText("여기에 YouTube 또는 Vimeo 링크를 붙여넣으세요...")
        self.url_combo.addItems(self.config.get("url_history"))
        self.url_combo.setCurrentIndex(-1)
        self.url_combo.lineEdit().setPlaceholderText("여기에 YouTube 또는 Vimeo 링크를 붙여넣으세요...")
        self.url_combo.setToolTip(
            "지원하는 사이트:\n"
            "- YouTube (영상, 재생목록, 채널)\n"
            "- Vimeo, Twitch, DailyMotion\n"
            "- Facebook, Instagram, TikTok\n"
            "- SoundCloud, Mixcloud 등 1000+ 사이트 지원"
        )
        
        self.paste_btn = QPushButton("붙여넣기")
        self.paste_btn.setToolTip("클립보드에서 주소를 가져옵니다.")
        self.paste_btn.clicked.connect(self.paste_url)
        
        self.add_btn = QPushButton("다운로드 시작")
        self.add_btn.setObjectName("ActionBtn")
        self.add_btn.setToolTip("목록에 작업을 추가하고 다운로드를 시작합니다.")
        self.add_btn.clicked.connect(self.add_task)

        input_layout.addWidget(self.url_combo, 1) # Stretch factor
        input_layout.addWidget(self.paste_btn)
        input_layout.addWidget(self.add_btn)
        
        main_layout.addWidget(input_group)

        # 2. Options Area
        opts_group = QGroupBox("설정 (Options)")
        opts_layout = QHBoxLayout(opts_group)
        opts_layout.setSpacing(15)
        
        # Path
        path_layout = QVBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setText(self.config.get("last_download_path"))
        self.path_input.setToolTip("파일이 저장될 폴더 경로입니다.")
        
        self.browse_btn = QPushButton("...")
        self.browse_btn.setObjectName("SmallBtn")
        self.browse_btn.setFixedWidth(35)
        self.browse_btn.setToolTip("저장 경로를 변경합니다.")
        self.browse_btn.clicked.connect(self.browse_folder)
        
        self.open_folder_btn = QPushButton("📂")
        self.open_folder_btn.setObjectName("SmallBtn")
        self.open_folder_btn.setFixedWidth(35)
        self.open_folder_btn.setToolTip("현재 저장 폴더를 엽니다.")
        self.open_folder_btn.clicked.connect(self.open_download_folder)

        # Format combo expanded
        self.format_combo = QComboBox()
        self.format_combo.addItems([
            "최고 화질 (MP4)", 
            "최고 화질 (MKV)", 
            "최고 화질 (WebM)",
            "오디오만 (MP3)",
            "오디오만 (WAV)"
        ])
        
        self.format_combo.setCurrentIndex(self.config.get("format_index"))
        self.format_combo.setToolTip("다운로드할 형식을 선택합니다.")
        
        # Auth
        self.auth_type_combo = QComboBox()
        self.auth_type_combo.addItems(["앱 내 로그인 (권장)", "Firefox", "파일 (Cookies.txt)", "인증 안 함"])
        
        # Restore Auth
        saved_auth = self.config.get("last_auth_method")
        index = self.auth_type_combo.findText(saved_auth) if saved_auth else 0
        if index >= 0:
            self.auth_type_combo.setCurrentIndex(index)
        else:
            self.auth_type_combo.setCurrentIndex(0) # Default to App Login

        self.auth_type_combo.setToolTip("연령 제한 영상을 위한 인증 방식입니다.\n'앱 내 로그인'을 추천합니다.")
        self.auth_type_combo.currentIndexChanged.connect(self.toggle_auth_input)
        
        self.auth_input = QWidget()
        self.auth_input_layout = QHBoxLayout(self.auth_input)
        self.auth_input_layout.setContentsMargins(0, 0, 0, 0)
        
        # --- Auth Widgets ---
        self.login_btn = QPushButton("로그인 (Log In)")
        self.login_btn.setToolTip("유튜브 로그인 창을 엽니다.")
        self.login_btn.clicked.connect(self.open_login_dialog)
        
        self.firefox_info = QLabel("(자동 감지)")
        
        self.cookie_file_edit = QLineEdit()
        self.cookie_file_edit.setPlaceholderText("cookies.txt 선택...")
        self.cookie_file_edit.setText(self.config.get("cookie_file_path"))
        self.cookie_file_btn = QPushButton("...")
        self.cookie_file_btn.setObjectName("SmallBtn")
        self.cookie_file_btn.setFixedWidth(30)
        self.cookie_file_btn.clicked.connect(self.browse_cookie_file)
        
        self.toggle_auth_input() # Refresh auth UI
        
        # Encoding Codec
        self.codec_combo = QComboBox()
        self.codec_combo.addItems(["변환 없음", "H264 (CPU)", "NVENC H264 (GPU)", "HEVC (H265)", "VP9"])
        saved_codec = self.config.get("last_codec")
        if saved_codec:
            idx = self.codec_combo.findText(saved_codec)
            if idx >= 0: self.codec_combo.setCurrentIndex(idx)
        self.codec_combo.setToolTip("재인코딩할 코덱을 선택합니다.")
        
        # Encoding Preset
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["기본 (Default)", "무손실 (Lossless)", "최소 손실 (High Quality)", "최대 압축 (Small Size)"])
        saved_preset = self.config.get("last_preset")
        if saved_preset:
            idx = self.preset_combo.findText(saved_preset)
            if idx >= 0: self.preset_combo.setCurrentIndex(idx)
        self.preset_combo.setToolTip("선택한 코덱에 적용할 화질/압축 프리셋입니다.")

        # Layout Assembly
        # Using VBox inside HBox for labelled fields? No, simpler flow
        
        path_group = QVBoxLayout()
        path_group.addWidget(QLabel("저장 경로 (Save Path):"))
        path_row = QHBoxLayout()
        path_row.addWidget(self.path_input)
        path_row.addWidget(self.browse_btn)
        path_row.addWidget(self.open_folder_btn)
        path_group.addLayout(path_row)
        
        opts_layout.addLayout(path_group, 2) # Give path more space

        # Row 2: Settings (Grid-like)
        settings_group = QVBoxLayout()
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("형식:"))
        r1.addWidget(self.format_combo)
        r1.addWidget(QLabel("인증:"))
        r1.addWidget(self.auth_type_combo)
        r1.addWidget(self.auth_input)
        
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("코덱:"))
        r2.addWidget(self.codec_combo)
        r2.addWidget(QLabel("품질:"))
        r2.addWidget(self.preset_combo)
        
        settings_group.addLayout(r1)
        settings_group.addLayout(r2)

        # Row 3: Advanced Options
        r3 = QHBoxLayout()
        self.overwrite_check = QCheckBox("덮어쓰기 (Overwrite)")
        self.overwrite_check.setChecked(False)
        self.overwrite_check.setToolTip("체크 시 이미 존재하는 파일을 덮어씁니다.\n해제 시 건너뜁니다.")
        
        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(0, 32)
        self.threads_spin.setValue(0) # Default 0 (Auto)
        self.threads_spin.setSuffix(" 개(0=Auto)")
        self.threads_spin.setToolTip("인코딩 시 사용할 CPU 스레드 개수입니다. (0=자동)")
        
        self.fragments_spin = QSpinBox()
        self.fragments_spin.setRange(1, 32)
        self.fragments_spin.setValue(5)
        self.fragments_spin.setSuffix(" 개")
        self.fragments_spin.setToolTip("다운로드 시 동시에 받을 조각 개수입니다. (기본 5)")
        
        r3.addWidget(self.overwrite_check)
        r3.addWidget(QLabel("인코딩 스레드:"))
        r3.addWidget(self.threads_spin)
        r3.addWidget(QLabel("다운로드 분할:"))
        r3.addWidget(self.fragments_spin)
        
        settings_group.addLayout(r3)
        
        opts_layout.addLayout(settings_group, 3)

        main_layout.addWidget(opts_group)

        # 3. Task List
        task_label = QLabel("작업 목록 (Tasks)")
        main_layout.addWidget(task_label)
        
        self.task_list = QListWidget()
        main_layout.addWidget(self.task_list)

    def closeEvent(self, event):
        # Save settings on exit
        self.config.set("last_download_path", self.path_input.text())
        self.config.set("last_auth_method", self.auth_type_combo.currentText())
        self.config.set("cookie_file_path", self.cookie_file_edit.text())
        self.config.set("last_codec", self.codec_combo.currentText())
        self.config.set("last_preset", self.preset_combo.currentText())
        self.config.set("format_index", self.format_combo.currentIndex())
        self.config.save_config()
        event.accept()

    @Slot()
    def open_download_folder(self):
        path = self.path_input.text()
        if os.path.exists(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            QMessageBox.warning(self, "오류", "폴더가 존재하지 않습니다.")

    @Slot()
    def toggle_auth_input(self):
        # Clear layout
        while self.auth_input_layout.count():
            item = self.auth_input_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
        
        auth_type = self.auth_type_combo.currentText()
        
        if auth_type == "앱 내 로그인 (권장)":
            self.auth_input_layout.addWidget(self.login_btn)
        elif auth_type == "Firefox":
            self.auth_input_layout.addWidget(self.firefox_info)
        elif auth_type == "파일 (Cookies.txt)":
            self.auth_input_layout.addWidget(self.cookie_file_edit)
            self.auth_input_layout.addWidget(self.cookie_file_btn)

    @Slot()
    def open_login_dialog(self):
        dialog = LoginDialog(self)
        dialog.exec()

    @Slot()
    def browse_cookie_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "쿠키 파일 선택 (Select Cookies File)", "", "Text Files (*.txt);;All Files (*)")
        if file_path:
            self.cookie_file_edit.setText(file_path)

    @Slot()
    def paste_url(self):
        self.logger.debug("paste_url triggered")
        clipboard = QApplication.clipboard()
        if clipboard:
            text = clipboard.text()
            self.logger.debug(f"Clipboard text: {text}")
            self.url_combo.setCurrentText(text)

    @Slot()
    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "다운로드 폴더 선택 (Select Folder)")
        if folder:
            self.path_input.setText(folder)

    def add_task(self):
        self.logger.debug("add_task triggered")
        url = self.url_combo.currentText().strip()
        path = self.path_input.text().strip()
        
        if not url:
            QMessageBox.warning(self, "입력 오류", "URL을 입력해주세요.")
            return

        # Add to history
        self.config.add_history(url)
        current_text = url
        self.url_combo.clear()
        self.url_combo.addItems(self.config.get("url_history"))
        self.url_combo.setCurrentText(current_text)

        if not os.path.exists(path):
            try:
                os.makedirs(path)
            except OSError:
                QMessageBox.warning(self, "경로 오류", "유효하지 않은 다운로드 경로입니다.")
                return

        # Get Options
        format_text = self.format_combo.currentText()
        audio_only = "오디오만" in format_text
        
        target_ext = None
        if "MKV" in format_text: target_ext = "mkv"
        elif "WebM" in format_text: target_ext = "webm"
        elif "MP4" in format_text: target_ext = "mp4"
        elif "MP3" in format_text: target_ext = "mp3"
        elif "WAV" in format_text: target_ext = "wav"

        # Auth Logic
        cookies = None
        auth_type = self.auth_type_combo.currentText()
        
        if auth_type == "앱 내 로그인 (권장)":
            cookie_path = os.path.abspath("libs/cookies/auth_cookies.txt")
            if os.path.exists(cookie_path):
                cookies = f"file:{cookie_path}"
            else:
                reply = QMessageBox.question(self, "로그인 필요", 
                                     "앱 내 로그인을 선택하셨지만 저장된 쿠키가 없습니다.\n"
                                     "지금 로그인하시겠습니까?",
                                     QMessageBox.Yes | QMessageBox.No)
                if reply == QMessageBox.Yes:
                    self.open_login_dialog()
                    if os.path.exists(cookie_path):
                        cookies = f"file:{cookie_path}"
                    else:
                        return 
                else:
                    return 
                    
        elif auth_type == "Firefox":
            cookies = "browser:firefox"
            
        elif auth_type == "파일 (Cookies.txt)":
            cookie_file = self.cookie_file_edit.text().strip()
            if cookie_file:
                 cookies = f"file:{cookie_file}"

        codec = self.codec_combo.currentText()
        preset = self.preset_combo.currentText()
        
        overwrite = self.overwrite_check.isChecked()
        threads = self.threads_spin.value()
        fragments = self.fragments_spin.value()

        # Create Task Widget
        task_widget = TaskWidget(url, path, audio_only, cookies, codec, preset, target_ext, overwrite, threads, fragments)
        task_widget.removed.connect(self.remove_task)
        
        # Add to List
        item = QListWidgetItem(self.task_list)
        item.setSizeHint(task_widget.sizeHint())
        
        self.task_list.addItem(item)
        self.task_list.setItemWidget(item, task_widget)
        
        # Start
        task_widget.start()
        
        # Clear Input? No, keep it in combo
        # self.url_input.clear()

    @Slot(QWidget)
    def remove_task(self, widget):
        for i in range(self.task_list.count()):
            item = self.task_list.item(i)
            if self.task_list.itemWidget(item) == widget:
                self.task_list.takeItem(i)
                break
