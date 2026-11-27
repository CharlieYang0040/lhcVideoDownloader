import re
from PySide6.QtCore import QTimer, QThread, QUrl, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from src.core.auth_manager import (
    BrowserCDPLoginSession,
    find_chromium_browsers,
    has_youtube_auth_cookies,
    write_netscape_cookies,
)
from src.ui.theme import APP_STYLESHEET
from src.utils.helpers import get_cookie_file_path


class _CDPLaunchWorker(QThread):
    launched = Signal()
    failed = Signal(str)

    def __init__(self, session, browser_exe, parent=None):
        super().__init__(parent)
        self.session = session
        self.browser_exe = browser_exe

    def run(self):
        try:
            self.session.start(self.browser_exe)
            self.launched.emit()
        except Exception as e:
            self.failed.emit(str(e))


class _CDPPollWorker(QThread):
    polled = Signal(bool, bool)  # browser_running, logged_in

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session

    def run(self):
        running = self.session.is_browser_running()
        logged_in = self.session.check_logged_in() if running else False
        self.polled.emit(running, logged_in)


class _CDPSaveWorker(QThread):
    saved = Signal(int)
    failed = Signal(str)

    def __init__(self, session, dest_path, parent=None):
        super().__init__(parent)
        self.session = session
        self.dest_path = dest_path

    def run(self):
        try:
            count = self.session.extract_and_save_cookies(self.dest_path)
            self.saved.emit(count)
        except Exception as e:
            self.failed.emit(str(e))


class LoginDialog(QDialog):
    LOGIN_URL = "https://accounts.google.com/ServiceLogin?service=youtube&continue=https%3A%2F%2Fwww.youtube.com%2F"
    ROBOTS_URL = "https://www.youtube.com/robots.txt"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("YouTube 로그인 (YouTube Login)")
        self.resize(580, 400)
        self.setStyleSheet(APP_STYLESHEET)

        self.browsers = find_chromium_browsers()
        self.cdp_session = BrowserCDPLoginSession()
        self._launch_worker = None
        self._poll_worker = None
        self._save_worker = None

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(1500)
        self._poll_timer.timeout.connect(self._poll_cdp_login)

        # Lazy QtWebEngine fallback state
        self._webengine_initialized = False
        self.web_profile = None
        self.web_page = None
        self.webview = None
        self.cookie_store = None
        self.collected_cookies = []
        self._waiting_for_robots = False
        self._fallback_timer = QTimer(self)
        self._fallback_timer.setSingleShot(True)
        self._fallback_timer.timeout.connect(self._collect_webengine_cookies)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(16, 16, 16, 16)
        root_layout.setSpacing(12)

        self.stack = QStackedWidget()
        root_layout.addWidget(self.stack)

        self.cdp_page = self._build_cdp_page()
        self.web_page_container = QWidget()
        self.web_page_layout = QVBoxLayout(self.web_page_container)
        self.web_page_layout.setContentsMargins(0, 0, 0, 0)
        self.web_page_layout.setSpacing(10)

        self.stack.addWidget(self.cdp_page)
        self.stack.addWidget(self.web_page_container)

        if self.browsers:
            self.stack.setCurrentWidget(self.cdp_page)
        else:
            self._switch_to_webengine()

    def _build_cdp_page(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        title = QLabel("안전한 외부 브라우저 로그인 (권장)")
        title.setObjectName("AppTitle")
        layout.addWidget(title)

        guide_panel = QFrame()
        guide_panel.setObjectName("Panel")
        guide_layout = QVBoxLayout(guide_panel)
        guide_layout.setContentsMargins(14, 12, 14, 12)
        guide_layout.setSpacing(8)

        guide_text = QLabel(
            "1. 아래에서 브라우저를 선택하고 '브라우저 열기'를 누르세요.\n"
            "   (현재 사용 중인 브라우저를 닫지 않아도 격리된 프로필로 안전하게 열립니다)\n"
            "2. 열린 창에서 Google 로그인 및 성인/연령 인증을 완료하세요.\n"
            "3. '쿠키 저장 및 완료'를 누르면 만료 방지를 위해 robots.txt 경로에서 쿠키를 안전하게 저장하고 창을 닫습니다."
        )
        guide_text.setWordWrap(True)
        guide_layout.addWidget(guide_text)

        browser_row = QHBoxLayout()
        browser_label = QLabel("로그인 브라우저:")
        browser_label.setObjectName("MutedLabel")
        self.browser_combo = QComboBox()
        for name, path in self.browsers:
            self.browser_combo.addItem(name, path)
        browser_row.addWidget(browser_label)
        browser_row.addWidget(self.browser_combo, 1)
        guide_layout.addLayout(browser_row)
        layout.addWidget(guide_panel)

        status_panel = QFrame()
        status_panel.setObjectName("AdvancedPanel")
        status_layout = QVBoxLayout(status_panel)
        status_layout.setContentsMargins(12, 10, 12, 10)
        self.cdp_status_label = QLabel("브라우저를 열어 YouTube에 로그인하세요.")
        self.cdp_status_label.setWordWrap(True)
        status_layout.addWidget(self.cdp_status_label)
        layout.addWidget(status_panel)

        layout.addStretch()

        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        self.open_browser_btn = QPushButton("브라우저 열기")
        self.open_browser_btn.setObjectName("ActionBtn")
        self.open_browser_btn.clicked.connect(self._launch_cdp_browser)

        self.cdp_save_btn = QPushButton("쿠키 저장 및 완료")
        self.cdp_save_btn.setObjectName("ActionBtn")
        self.cdp_save_btn.setEnabled(False)
        self.cdp_save_btn.clicked.connect(self._save_cdp_cookies)

        action_row.addWidget(self.open_browser_btn)
        action_row.addWidget(self.cdp_save_btn)
        layout.addLayout(action_row)

        footer_row = QHBoxLayout()
        self.use_webengine_btn = QPushButton("내장 브라우저로 로그인")
        self.use_webengine_btn.setObjectName("SecondaryButton")
        self.use_webengine_btn.clicked.connect(self._switch_to_webengine)

        self.cdp_close_btn = QPushButton("닫기")
        self.cdp_close_btn.setObjectName("SecondaryButton")
        self.cdp_close_btn.clicked.connect(self.reject)

        footer_row.addWidget(self.use_webengine_btn)
        footer_row.addStretch()
        footer_row.addWidget(self.cdp_close_btn)
        layout.addLayout(footer_row)

        return container

    def _init_webengine_page(self):
        if self._webengine_initialized:
            return
        from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
        from PySide6.QtWebEngineWidgets import QWebEngineView

        info_label = QLabel(
            "내장 브라우저 로그인 모드입니다. Google 로그인 및 성인 인증 완료 후 아래 '로그인 완료 및 쿠키 저장'을 누르세요."
        )
        info_label.setWordWrap(True)
        info_label.setObjectName("MutedLabel")
        self.web_page_layout.addWidget(info_label)

        # Off-the-record isolated profile avoids persisting active tabs that rotate cookies
        self.web_profile = QWebEngineProfile(self)
        ua = self.web_profile.httpUserAgent()
        clean_ua = re.sub(r"QtWebEngine/\S+\s*", "", ua).strip()
        if clean_ua:
            self.web_profile.setHttpUserAgent(clean_ua)

        self.webview = QWebEngineView(self)
        self.web_page = QWebEnginePage(self.web_profile, self.webview)
        self.webview.setPage(self.web_page)
        self.webview.loadFinished.connect(self._on_webengine_load_finished)
        self.webview.setUrl(QUrl(self.LOGIN_URL))
        self.web_page_layout.addWidget(self.webview, 1)

        btn_row = QHBoxLayout()
        if self.browsers:
            back_btn = QPushButton("외부 브라우저 로그인으로")
            back_btn.setObjectName("SecondaryButton")
            back_btn.clicked.connect(lambda: self.stack.setCurrentWidget(self.cdp_page))
            btn_row.addWidget(back_btn)

        self.web_save_btn = QPushButton("로그인 완료 및 쿠키 저장")
        self.web_save_btn.setObjectName("ActionBtn")
        self.web_save_btn.clicked.connect(self.save_cookies)

        close_btn = QPushButton("닫기")
        close_btn.setObjectName("SecondaryButton")
        close_btn.clicked.connect(self.reject)

        btn_row.addWidget(self.web_save_btn, 1)
        btn_row.addWidget(close_btn)
        self.web_page_layout.addLayout(btn_row)
        self._webengine_initialized = True

    @Slot()
    def _switch_to_webengine(self):
        self._poll_timer.stop()
        self.cdp_session.close()
        self._init_webengine_page()
        self.resize(1024, 768)
        self.stack.setCurrentWidget(self.web_page_container)

    @Slot()
    def _launch_cdp_browser(self):
        browser_exe = self.browser_combo.currentData()
        if not browser_exe:
            QMessageBox.warning(self, "오류", "선택된 브라우저 실행 파일을 찾을 수 없습니다.")
            return

        self.open_browser_btn.setEnabled(False)
        self.cdp_save_btn.setEnabled(False)
        self.cdp_status_label.setStyleSheet("")
        self.cdp_status_label.setText("격리된 로그인 브라우저를 시작하는 중...")

        self._launch_worker = _CDPLaunchWorker(self.cdp_session, browser_exe, self)
        self._launch_worker.launched.connect(self._on_cdp_launched)
        self._launch_worker.failed.connect(self._on_cdp_launch_failed)
        self._launch_worker.start()

    @Slot()
    def _on_cdp_launched(self):
        self.open_browser_btn.setEnabled(True)
        self.open_browser_btn.setText("브라우저 다시 열기")
        self.cdp_save_btn.setEnabled(True)
        self.cdp_status_label.setStyleSheet("")
        self.cdp_status_label.setText(
            "브라우저에서 로그인 진행 중... (성인인증이 필요하면 함께 완료하세요)"
        )
        self._poll_timer.start()

    @Slot(str)
    def _on_cdp_launch_failed(self, err):
        self.open_browser_btn.setEnabled(True)
        self.cdp_save_btn.setEnabled(False)
        self.cdp_status_label.setStyleSheet("color: #ffaaa5;")
        self.cdp_status_label.setText(f"브라우저 실행 실패: {err}")

    @Slot()
    def _poll_cdp_login(self):
        if self._poll_worker and self._poll_worker.isRunning():
            return
        self._poll_worker = _CDPPollWorker(self.cdp_session, self)
        self._poll_worker.polled.connect(self._on_cdp_polled)
        self._poll_worker.start()

    @Slot(bool, bool)
    def _on_cdp_polled(self, running, logged_in):
        if not running:
            self._poll_timer.stop()
            self.cdp_save_btn.setEnabled(False)
            self.cdp_status_label.setStyleSheet("color: #ffd28a;")
            self.cdp_status_label.setText(
                "브라우저가 닫혔습니다. '브라우저 다시 열기'를 눌러 로그인한 뒤 저장해주세요."
            )
            return

        if logged_in:
            self.cdp_status_label.setStyleSheet("color: #9ff0b5; font-weight: bold;")
            self.cdp_status_label.setText(
                "✓ YouTube 로그인 감지됨! 아래 '쿠키 저장 및 완료'를 누르세요."
            )
        else:
            self.cdp_status_label.setStyleSheet("")
            self.cdp_status_label.setText(
                "브라우저에서 로그인 진행 중... (성인인증이 필요하면 함께 완료하세요)"
            )

    @Slot()
    def _save_cdp_cookies(self):
        self._poll_timer.stop()
        self.open_browser_btn.setEnabled(False)
        self.cdp_save_btn.setEnabled(False)
        self.cdp_status_label.setStyleSheet("")
        self.cdp_status_label.setText("robots.txt 페이지에서 쿠키를 안전하게 추출하고 있습니다...")

        self._save_worker = _CDPSaveWorker(self.cdp_session, get_cookie_file_path(), self)
        self._save_worker.saved.connect(self._on_cdp_saved)
        self._save_worker.failed.connect(self._on_cdp_save_failed)
        self._save_worker.start()

    @Slot(int)
    def _on_cdp_saved(self, count):
        QMessageBox.information(
            self,
            "성공",
            f"YouTube 로그인 쿠키({count}개)가 안전하게 저장되었습니다!\n"
            "이제 성인 인증 영상도 자동으로 다운로드할 수 있습니다.",
        )
        self.accept()

    @Slot(str)
    def _on_cdp_save_failed(self, err):
        self.open_browser_btn.setEnabled(True)
        self.cdp_save_btn.setEnabled(self.cdp_session.is_browser_running())
        if self.cdp_session.is_browser_running():
            self._poll_timer.start()
        self.cdp_status_label.setStyleSheet("color: #ffd28a;")
        self.cdp_status_label.setText(err)
        QMessageBox.warning(self, "쿠키 저장 안내", err)

    # --- QtWebEngine Fallback ---
    @Slot()
    def save_cookies(self):
        if not self.webview:
            return
        self.web_save_btn.setText("쿠키 추출 중... 잠시만 기다려주세요...")
        self.web_save_btn.setEnabled(False)
        self._waiting_for_robots = True
        self._fallback_timer.start(5000)
        self.webview.setUrl(QUrl(self.ROBOTS_URL))

    @Slot(bool)
    def _on_webengine_load_finished(self, ok):
        if not self._waiting_for_robots:
            return
        self._waiting_for_robots = False
        self._fallback_timer.stop()
        self._collect_webengine_cookies()

    @Slot()
    def _collect_webengine_cookies(self):
        self._waiting_for_robots = False
        if not self.web_profile:
            return

        self.cookie_store = self.web_profile.cookieStore()
        self.collected_cookies = []
        try:
            self.cookie_store.cookieAdded.disconnect(self._handle_webengine_cookie)
        except (TypeError, RuntimeError):
            pass
        self.cookie_store.cookieAdded.connect(self._handle_webengine_cookie)
        self.cookie_store.loadAllCookies()
        QTimer.singleShot(1200, self.finalize_save)

    def _handle_webengine_cookie(self, cookie):
        self.collected_cookies.append({
            "domain": cookie.domain(),
            "path": cookie.path() or "/",
            "secure": cookie.isSecure(),
            "expires": int(cookie.expirationDate().toSecsSinceEpoch()) if not cookie.expirationDate().isNull() else 0,
            "name": cookie.name().data().decode("utf-8", errors="replace"),
            "value": cookie.value().data().decode("utf-8", errors="replace"),
        })

    def finalize_save(self):
        if self.cookie_store is not None:
            try:
                self.cookie_store.cookieAdded.disconnect(self._handle_webengine_cookie)
            except (TypeError, RuntimeError):
                pass

        if not has_youtube_auth_cookies(self.collected_cookies):
            QMessageBox.warning(
                self,
                "로그인 확인 필요",
                "유효한 YouTube 로그인 쿠키를 찾지 못했습니다.\n로그인을 완료한 뒤 다시 시도해주세요.",
            )
            self.web_save_btn.setText("로그인 완료 및 쿠키 저장")
            self.web_save_btn.setEnabled(True)
            self.webview.setUrl(QUrl(self.LOGIN_URL))
            return

        cookie_file_path = get_cookie_file_path()
        try:
            count = write_netscape_cookies(self.collected_cookies, cookie_file_path)
            QMessageBox.information(
                self,
                "성공",
                f"쿠키({count}개)가 성공적으로 저장되었습니다!\n이제 성인 인증 영상도 다운로드할 수 있습니다.",
            )
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "오류", f"쿠키 저장 실패: {str(e)}")
            self.web_save_btn.setText("다시 시도")
            self.web_save_btn.setEnabled(True)

    def _cleanup_resources(self):
        self._poll_timer.stop()
        self._fallback_timer.stop()
        for worker in (self._launch_worker, self._poll_worker, self._save_worker):
            if worker and worker.isRunning():
                worker.wait(2000)
        self.cdp_session.close()

        if self._webengine_initialized:
            if self.webview is not None:
                self.webview.setPage(None)
            if self.web_page is not None:
                self.web_page.deleteLater()
                self.web_page = None
            if self.web_profile is not None:
                self.web_profile.deleteLater()
                self.web_profile = None
            self._webengine_initialized = False

    def done(self, result):
        self._cleanup_resources()
        super().done(result)

    def closeEvent(self, event):
        self._cleanup_resources()
        super().closeEvent(event)
