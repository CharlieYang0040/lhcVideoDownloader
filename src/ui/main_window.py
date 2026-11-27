import os
import logging
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                               QPushButton, QLineEdit, QListWidget, QListWidgetItem,
                               QComboBox, QLabel, QFileDialog, QMessageBox, QApplication,
                               QCheckBox, QSpinBox, QFrame, QGridLayout, QToolButton, QStyle)
from PySide6.QtCore import Slot, QSize, QUrl, Qt
from PySide6.QtGui import QDesktopServices
from src.ui.task_widget import TaskWidget
from src.ui.login_dialog import LoginDialog
from src.ui.theme import APP_STYLESHEET
from src.utils.config import ConfigManager
from src.core.auth_manager import clear_saved_cookies, inspect_cookie_file
from src.core.downloader import YtDlpUpdateThread

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.debug("Initializing MainWindow...")
        self.setWindowTitle("LHC Video Downloader")
        self.resize(1000, 720)

        # Load Config
        self.config = ConfigManager()

        self.setStyleSheet(APP_STYLESHEET)

        # Main Layout
        central_widget = QWidget()
        central_widget.setObjectName("Root")
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(14)
        main_layout.setContentsMargins(18, 18, 18, 18)

        header_layout = QHBoxLayout()
        title_label = QLabel("LHC Video Downloader")
        title_label.setObjectName("AppTitle")
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        self.header_auth_label = QLabel("YouTube: 확인 중")
        self.header_auth_label.setObjectName("MutedLabel")
        self.header_login_btn = QPushButton("YouTube 로그인")
        self.header_login_btn.setObjectName("QueueButton")
        self.header_login_btn.setCursor(Qt.PointingHandCursor)
        self.header_login_btn.setToolTip("성인 인증/연령 제한 영상 다운로드를 위해 YouTube에 로그인합니다.")
        self.header_login_btn.clicked.connect(self.open_login_dialog)
        self.ytdlp_status_label = QLabel("yt-dlp 업데이트 확인 중...")
        self.ytdlp_status_label.setObjectName("MutedLabel")
        header_layout.addWidget(self.header_auth_label, alignment=Qt.AlignVCenter)
        header_layout.addWidget(self.header_login_btn, alignment=Qt.AlignVCenter)
        header_layout.addSpacing(12)
        header_layout.addWidget(self.ytdlp_status_label, alignment=Qt.AlignVCenter | Qt.AlignRight)
        main_layout.addLayout(header_layout)

        # 1. Command Area
        input_panel = QFrame()
        input_panel.setObjectName("Panel")
        input_layout = QVBoxLayout(input_panel)
        input_layout.setContentsMargins(14, 12, 14, 14)
        input_layout.setSpacing(10)
        input_layout.addWidget(self.section_label("Download"))

        # URL History Combo
        self.url_combo = QComboBox()
        self.url_combo.setEditable(True)
        self.url_combo.setPlaceholderText("URL 입력")
        self.url_combo.addItems(self.config.get("url_history"))
        self.url_combo.setCurrentIndex(-1)
        self.url_combo.lineEdit().setPlaceholderText("URL 입력")
        self.url_combo.setToolTip(
            "지원하는 사이트:\n"
            "- YouTube (영상, 재생목록, 채널)\n"
            "- Vimeo, Twitch, DailyMotion\n"
            "- Facebook, Instagram, TikTok\n"
            "- SoundCloud, Mixcloud 등 1000+ 사이트 지원"
        )

        self.paste_btn = QPushButton("붙여넣기")
        self.paste_btn.setObjectName("SecondaryButton")
        self.paste_btn.setToolTip("클립보드에서 주소를 가져옵니다.")
        self.paste_btn.clicked.connect(self.paste_url)

        self.add_btn = QPushButton("다운로드")
        self.add_btn.setObjectName("ActionBtn")
        self.add_btn.setToolTip("목록에 작업을 추가하고 다운로드를 시작합니다.")
        self.add_btn.clicked.connect(self.add_task)

        command_row = QHBoxLayout()
        command_row.setSpacing(8)
        command_row.addWidget(self.url_combo, 1)
        command_row.addWidget(self.paste_btn)
        command_row.addWidget(self.add_btn)
        input_layout.addLayout(command_row)

        main_layout.addWidget(input_panel)

        # 2. Options Area
        opts_panel = QFrame()
        opts_panel.setObjectName("Panel")
        opts_layout = QVBoxLayout(opts_panel)
        opts_layout.setContentsMargins(14, 12, 14, 14)
        opts_layout.setSpacing(10)
        opts_layout.addWidget(self.section_label("Options"))

        # Path
        self.path_input = QLineEdit()
        self.path_input.setText(self.config.get("last_download_path"))
        self.path_input.setToolTip("파일이 저장될 폴더 경로입니다.")

        self.browse_btn = QToolButton()
        self.browse_btn.setObjectName("IconButton")
        self.browse_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self.browse_btn.setIconSize(QSize(16, 16))
        self.browse_btn.setToolTip("저장 경로를 변경합니다.")
        self.browse_btn.clicked.connect(self.browse_folder)

        self.open_folder_btn = QToolButton()
        self.open_folder_btn.setObjectName("IconButton")
        self.open_folder_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
        self.open_folder_btn.setIconSize(QSize(16, 16))
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
        self.auth_type_combo.addItems([
            "자동 (필요 시 인증 · 권장)",
            "저장된 쿠키 항상 사용",
            "Firefox (자동)",
            "파일 (Cookies.txt)",
            "인증 안 함",
        ])

        # Restore Auth (migrate legacy values)
        saved_auth = self.config.get("last_auth_method")
        auth_migration = {
            "": "자동 (필요 시 인증 · 권장)",
            None: "자동 (필요 시 인증 · 권장)",
            "None": "자동 (필요 시 인증 · 권장)",
            "앱 내 로그인 (권장)": "저장된 쿠키 항상 사용",
            "Firefox": "Firefox (자동)",
        }
        saved_auth = auth_migration.get(saved_auth, saved_auth)

        index = self.auth_type_combo.findText(saved_auth)
        if index >= 0:
            self.auth_type_combo.setCurrentIndex(index)
        else:
            self.auth_type_combo.setCurrentIndex(0)

        self.auth_type_combo.setToolTip(
            "성인 인증/연령 제한 영상을 위한 인증 방식입니다.\n"
            "'자동' 모드는 일반 영상을 쿠키 없이 받고, 필요할 때만 저장된 쿠키로 자동 재시도합니다."
        )
        self.auth_type_combo.currentIndexChanged.connect(self.toggle_auth_input)

        self.auth_input = QWidget()
        self.auth_input_layout = QHBoxLayout(self.auth_input)
        self.auth_input_layout.setContentsMargins(0, 0, 0, 0)
        self.auth_input_layout.setSpacing(6)

        # --- Auth Widgets ---
        self.login_btn = QPushButton("YouTube 로그인")
        self.login_btn.setObjectName("SecondaryButton")
        self.login_btn.setToolTip("격리된 브라우저를 통해 안전하게 YouTube 로그인 쿠키를 저장합니다.")
        self.login_btn.clicked.connect(self.open_login_dialog)

        self.logout_btn = QPushButton("로그아웃")
        self.logout_btn.setObjectName("SecondaryButton")
        self.logout_btn.setToolTip("저장된 YouTube 로그인 쿠키를 삭제합니다.")
        self.logout_btn.clicked.connect(self.clear_cookies)

        self.cookie_status_info = QLabel("")
        self.cookie_status_info.setObjectName("MutedLabel")

        self.firefox_info = QLabel("(자동 감지 · App-Bound 영향 없음)")
        self.firefox_info.setObjectName("MutedLabel")

        self.cookie_file_edit = QLineEdit()
        self.cookie_file_edit.setPlaceholderText("cookies.txt 선택...")
        self.cookie_file_edit.setText(self.config.get("cookie_file_path"))
        self.cookie_file_btn = QToolButton()
        self.cookie_file_btn.setObjectName("IconButton")
        self.cookie_file_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon))
        self.cookie_file_btn.setIconSize(QSize(16, 16))
        self.cookie_file_btn.clicked.connect(self.browse_cookie_file)

        self.toggle_auth_input()  # Refresh auth UI
        self.refresh_auth_status()

        # Encoding Codec
        self.codec_combo = QComboBox()
        self.codec_combo.addItems(["변환 없음", "H264 (CPU)", "NVENC H264 (GPU)", "HEVC (H265)", "VP9"])
        saved_codec = self.config.get("last_codec")
        if saved_codec:
            idx = self.codec_combo.findText(saved_codec)
            if idx >= 0: self.codec_combo.setCurrentIndex(idx)
        self.codec_combo.setToolTip("시간이 오래 걸릴 수 있으니 재생에 문제가 있을 경우 사용해주세요.")

        # Encoding Preset
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["기본 (Default)", "무손실 (Lossless)", "최소 손실 (High Quality)", "최대 압축 (Small Size)"])
        saved_preset = self.config.get("last_preset")
        if saved_preset:
            idx = self.preset_combo.findText(saved_preset)
            if idx >= 0: self.preset_combo.setCurrentIndex(idx)
        self.preset_combo.setToolTip("선택한 코덱에 적용할 화질/압축 프리셋입니다.")

        # Layout Assembly
        basic_grid = QGridLayout()
        basic_grid.setHorizontalSpacing(12)
        basic_grid.setVerticalSpacing(10)

        path_widget = QWidget()
        path_row = QHBoxLayout()
        path_row.setContentsMargins(0, 0, 0, 0)
        path_row.setSpacing(6)
        path_row.addWidget(self.path_input)
        path_row.addWidget(self.browse_btn)
        path_row.addWidget(self.open_folder_btn)
        path_widget.setLayout(path_row)

        self.format_combo.setMinimumWidth(190)
        self.format_combo.setMaximumWidth(240)
        self.auth_type_combo.setMinimumWidth(180)
        self.auth_type_combo.setMaximumWidth(230)
        self.codec_combo.setMinimumWidth(180)
        self.codec_combo.setMaximumWidth(230)
        self.preset_combo.setMinimumWidth(220)
        self.preset_combo.setMaximumWidth(280)

        basic_grid.addWidget(self.field_block("저장 경로", path_widget), 0, 0, 1, 3)
        basic_grid.addWidget(self.field_block("형식", self.format_combo), 0, 3)
        basic_grid.setColumnStretch(0, 4)
        basic_grid.setColumnStretch(3, 1)
        opts_layout.addLayout(basic_grid)

        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setObjectName("AdvancedToggle")
        self.advanced_toggle.setText("Advanced")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setChecked(False)
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.advanced_toggle.setArrowType(Qt.RightArrow)
        self.advanced_toggle.toggled.connect(self.toggle_advanced_options)
        opts_layout.addWidget(self.advanced_toggle, alignment=Qt.AlignLeft)

        self.advanced_frame = QFrame()
        self.advanced_frame.setObjectName("AdvancedPanel")
        advanced_layout = QGridLayout(self.advanced_frame)
        advanced_layout.setContentsMargins(10, 10, 10, 10)
        advanced_layout.setHorizontalSpacing(12)
        advanced_layout.setVerticalSpacing(10)
        self.overwrite_check = QCheckBox("덮어쓰기 (Overwrite)")
        self.overwrite_check.setChecked(False)
        self.overwrite_check.setToolTip("체크 시 이미 존재하는 파일을 덮어씁니다.\n해제 시 건너뜁니다.")

        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(0, 32)
        self.threads_spin.setValue(0) # Default 0 (Auto)
        self.threads_spin.setSuffix(" 개(0=Auto)")
        self.threads_spin.setMinimumWidth(120)
        self.threads_spin.setMaximumWidth(150)
        self.threads_spin.setToolTip("인코딩 시 사용할 CPU 스레드 개수입니다. (0=자동)")

        self.fragments_spin = QSpinBox()
        self.fragments_spin.setRange(1, 32)
        self.fragments_spin.setValue(5)
        self.fragments_spin.setSuffix(" 개")
        self.fragments_spin.setMinimumWidth(110)
        self.fragments_spin.setMaximumWidth(140)
        self.fragments_spin.setToolTip("다운로드 시 동시에 받을 조각 개수입니다. (기본 5)")

        advanced_layout.addWidget(self.field_block("인증", self.auth_type_combo), 0, 0)
        advanced_layout.addWidget(self.field_block("인증 옵션", self.auth_input), 0, 1)
        advanced_layout.addWidget(self.field_block("추가 인코딩 코덱", self.codec_combo), 0, 2)
        advanced_layout.addWidget(self.field_block("품질", self.preset_combo), 0, 3)
        advanced_layout.addWidget(self.field_block("파일 처리", self.overwrite_check), 1, 0)
        advanced_layout.addWidget(self.field_block("인코딩 스레드", self.threads_spin), 1, 1)
        advanced_layout.addWidget(self.field_block("다운로드 분할", self.fragments_spin), 1, 2)
        advanced_layout.setColumnStretch(0, 0)
        advanced_layout.setColumnStretch(1, 1)
        advanced_layout.setColumnStretch(2, 0)
        advanced_layout.setColumnStretch(3, 0)
        self.advanced_frame.setVisible(False)
        opts_layout.addWidget(self.advanced_frame)

        main_layout.addWidget(opts_panel)

        # 3. Task List
        task_label = self.section_label("Queue")
        main_layout.addWidget(task_label)

        self.task_list = QListWidget()
        self.task_list.setSpacing(6)
        main_layout.addWidget(self.task_list)

        # Startup yt-dlp update check (once per app launch)
        self.ytdlp_update_thread = YtDlpUpdateThread(self)
        self.ytdlp_update_thread.status_changed.connect(self.ytdlp_status_label.setText)
        self.ytdlp_update_thread.log_message.connect(self.logger.info)
        self.ytdlp_update_thread.start()

    def section_label(self, text):
        label = QLabel(text)
        label.setObjectName("SectionTitle")
        return label

    def field_label(self, text):
        label = QLabel(text)
        label.setObjectName("MutedLabel")
        return label

    def field_block(self, text, widget):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.field_label(text))
        layout.addWidget(widget)
        return container

    @Slot(bool)
    def toggle_advanced_options(self, checked):
        self.advanced_frame.setVisible(checked)
        self.advanced_toggle.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)

    def closeEvent(self, event):
        running_tasks = []
        for i in range(self.task_list.count()):
            item = self.task_list.item(i)
            task_widget = self.task_list.itemWidget(item)
            if task_widget and task_widget.is_active():
                running_tasks.append(task_widget)

        if running_tasks:
            reply = QMessageBox.question(
                self,
                "작업 진행 중",
                "진행 중인 다운로드가 있습니다.\n종료하면 실행 중인 작업이 취소됩니다. 종료하시겠습니까?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return

            for task_widget in running_tasks:
                task_widget.stop_for_shutdown()

        if hasattr(self, "ytdlp_update_thread") and self.ytdlp_update_thread.isRunning():
            self.ytdlp_update_thread.stop()
            self.ytdlp_update_thread.wait(3000)

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
    def refresh_auth_status(self):
        info = inspect_cookie_file()
        if info["valid"]:
            self.header_auth_label.setStyleSheet("color: #9ff0b5;")
            self.header_auth_label.setText(f"YouTube: {info['summary']}")
            self.header_login_btn.setText("재로그인")
        elif info["expired"]:
            self.header_auth_label.setStyleSheet("color: #ffd28a;")
            self.header_auth_label.setText("YouTube: 쿠키 만료됨")
            self.header_login_btn.setText("다시 로그인")
        else:
            self.header_auth_label.setStyleSheet("")
            self.header_auth_label.setText("YouTube: 로그인 안 됨")
            self.header_login_btn.setText("YouTube 로그인")

        self.cookie_status_info.setText(info["summary"])
        self.logout_btn.setEnabled(info["exists"])

    @Slot()
    def toggle_auth_input(self):
        # Clear layout
        while self.auth_input_layout.count():
            item = self.auth_input_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)

        auth_type = self.auth_type_combo.currentText()

        if auth_type in ("자동 (필요 시 인증 · 권장)", "저장된 쿠키 항상 사용"):
            self.auth_input_layout.addWidget(self.login_btn)
            self.auth_input_layout.addWidget(self.logout_btn)
            self.auth_input_layout.addWidget(self.cookie_status_info)
        elif auth_type == "Firefox (자동)":
            self.auth_input_layout.addWidget(self.firefox_info)
        elif auth_type == "파일 (Cookies.txt)":
            self.auth_input_layout.addWidget(self.cookie_file_edit)
            self.auth_input_layout.addWidget(self.cookie_file_btn)

    @Slot()
    def open_login_dialog(self):
        dialog = LoginDialog(self)
        accepted = dialog.exec() == LoginDialog.DialogCode.Accepted
        self.refresh_auth_status()
        return accepted

    @Slot()
    def clear_cookies(self):
        reply = QMessageBox.question(
            self,
            "로그아웃",
            "저장된 YouTube 로그인 쿠키를 삭제하시겠습니까?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            clear_saved_cookies()
            self.refresh_auth_status()

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
        fallback_cookies = None
        auth_type = self.auth_type_combo.currentText()

        if auth_type == "자동 (필요 시 인증 · 권장)":
            cookie_info = inspect_cookie_file()
            if cookie_info["valid"]:
                fallback_cookies = f"file:{cookie_info['path']}"

        elif auth_type == "저장된 쿠키 항상 사용":
            cookie_info = inspect_cookie_file()
            if cookie_info["valid"]:
                cookies = f"file:{cookie_info['path']}"
            else:
                reply = QMessageBox.question(
                    self,
                    "로그인 필요",
                    "저장된 쿠키 항상 사용을 선택하셨지만 유효한 로그인 쿠키가 없습니다.\n"
                    "지금 로그인하시겠습니까?",
                    QMessageBox.Yes | QMessageBox.No,
                )
                if reply == QMessageBox.Yes:
                    self.open_login_dialog()
                    cookie_info = inspect_cookie_file()
                    if cookie_info["valid"]:
                        cookies = f"file:{cookie_info['path']}"
                    else:
                        return
                else:
                    return

        elif auth_type == "Firefox (자동)":
            cookies = "browser:firefox"

        elif auth_type == "파일 (Cookies.txt)":
            cookie_file = self.cookie_file_edit.text().strip()
            if cookie_file:
                cookies = f"file:{cookie_file}"

        codec = self.codec_combo.currentText()
        preset = self.preset_combo.currentText()

        if not audio_only and target_ext == "webm" and codec not in ("변환 없음", "None", "VP9"):
            QMessageBox.warning(
                self,
                "형식/코덱 호환 오류",
                "WebM 형식은 VP9 코덱 또는 '변환 없음'만 지원합니다.\n"
                "형식을 MP4/MKV로 변경하거나 코덱을 VP9/변환 없음으로 선택해주세요."
            )
            return

        overwrite = self.overwrite_check.isChecked()
        threads = self.threads_spin.value()
        fragments = self.fragments_spin.value()

        # Create Task Widget
        task_widget = TaskWidget(
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
        task_widget.removed.connect(self.remove_task)
        task_widget.login_retry_requested.connect(self.handle_login_and_retry)

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
    def handle_login_and_retry(self, task_widget):
        if self.open_login_dialog():
            info = inspect_cookie_file()
            if info["valid"]:
                task_widget.retry_with_cookies(f"file:{info['path']}")

    @Slot(QWidget)
    def remove_task(self, widget):
        for i in range(self.task_list.count()):
            item = self.task_list.item(i)
            if self.task_list.itemWidget(item) == widget:
                self.task_list.takeItem(i)
                break
