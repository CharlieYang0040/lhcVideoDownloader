from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLabel, QMessageBox
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineCookieStore, QWebEngineProfile
from PySide6.QtCore import QUrl, Signal, Qt, QTimer
import os

from app.config_manager import ConfigManager
import logging

# 모듈 로거
log = logging.getLogger(__name__)


class YouTubeAuthWindow(QWidget):
    """YouTube 로그인을 위한 웹뷰 창 클래스.

    Google 로그인 페이지를 표시하고, 로그인 성공 시 쿠키를 수집하여
    ConfigManager를 통해 저장합니다.
    """
    login_completed = Signal()  # 로그인 성공 시
    login_error = Signal(str)  # 로그인 실패 또는 오류 시

    # 생성자에서 config_manager 주입 받기
    def __init__(self, config_manager: ConfigManager, parent=None):
        """YouTubeAuthWindow 초기화.

        Args:
            config_manager (ConfigManager): 쿠키 저장을 위한 ConfigManager 인스턴스.
            parent (QWidget, optional): 부모 위젯. Defaults to None.
        """
        super().__init__(parent)
        log.info("Initializing YouTubeAuthWindow...")

        # 주입받은 ConfigManager 사용
        self.config_manager = config_manager

        self.setWindowTitle("YouTube 로그인")
        self.setGeometry(100, 100, 800, 600)

        layout = QVBoxLayout()

        self.label = QLabel("Google 계정으로 로그인해주세요")
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label)

        try:
            log.debug("Creating QWebEngineView...")
            self.webview = QWebEngineView()
            log.debug("QWebEngineView created.")
            # Google 로그인 URL 설정
            self.webview.setUrl(
                QUrl("https://accounts.google.com/signin/v2/identifier?service=youtube")
            )
            log.debug("Loading Google Sign-In URL.")

            # 쿠키 스토어 연결
            # 웹뷰 페이지의 프로필에서 쿠키 스토어 가져오기
            # 주의: profile()이 None일 수 있음 (오류 시 확인 필요)
            profile = self.webview.page().profile()
            if profile:
                self.cookie_store = profile.cookieStore()
                self.cookie_store.cookieAdded.connect(self.on_cookie_added)
                log.debug("Cookie store connected.")
            else:
                log.error(
                    "Failed to get QWebEngineProfile. Cookie handling might fail."
                )
                # 사용자에게 오류 알림
                QMessageBox.critical(
                    self,
                    "오류",
                    "웹 프로필을 가져올 수 없습니다. 쿠키 처리에 문제가 발생할 수 있습니다.",
                )
                # 오류 시 진행 중단 또는 다른 처리
                # QTimer.singleShot(0, self.close)
                # return # 여기서 종료하면 웹뷰가 표시되지 않을 수 있음

            layout.addWidget(self.webview)
            self.setLayout(layout)

            # 상태 변수 초기화
            self._collected_cookies = []  # Netscape 형식 데이터 저장
            self._login_check_timer = None  # 타이머 참조
            self.webview.loadFinished.connect(self.on_load_finished)
            self._redirect_to_youtube_attempted = False
            self._has_essential_login_cookie = False  # 로그인 확인용 플래그

            log.info("YouTubeAuthWindow UI initialized.")
            # self.show()는 외부에서 호출되도록 변경 (선택적)
            # 또는 생성자에서 show() 유지 시 오류 처리 강화

        except Exception as e:
            log.exception("Error during YouTubeAuthWindow initialization")
            error_msg = f"로그인 창 초기화 중 오류 발생: {e}\nQtWebEngine 구성 요소를 확인하세요."
            QMessageBox.critical(self, "초기화 오류", error_msg)
            # 오류 시 즉시 창 닫기 (메모리 누수 방지)
            QTimer.singleShot(0, self.close)

    def on_cookie_added(self, cookie):
        """QWebEngineCookieStore에서 쿠키가 추가될 때 호출되는 슬롯.

        YouTube 또는 Google 관련 쿠키를 수집하고 Netscape 형식으로 변환하여 저장합니다.
        로그인 상태 확인을 위한 플래그(_has_essential_login_cookie)를 설정합니다.

        Args:
            cookie (QNetworkCookie): 추가된 쿠키 객체.
        """
        domain = cookie.domain()
        # YouTube 또는 Google 관련 도메인만 처리
        if not any(d in domain for d in [".youtube.com", ".google.com"]):
            return

        name = cookie.name().data().decode("utf-8", errors="ignore")
        value = cookie.value().data().decode("utf-8", errors="ignore")
        path = cookie.path()
        secure = cookie.isSecure()
        # http_only = cookie.isHttpOnly() # Netscape 형식에는 없음
        expires = (
            int(cookie.expirationDate().toSecsSinceEpoch())
            if not cookie.isSessionCookie()
            else 0
        )

        # Netscape 형식 데이터 생성
        cookie_data = {
            "domain": domain,
            "flag": "TRUE" if domain.startswith(".") else "FALSE",
            "path": path,
            "secure": "TRUE" if secure else "FALSE",
            "expiration": expires,
            "name": name,
            "value": value,
        }

        # 기존 쿠키 업데이트 또는 추가 (리스트 내포 대신 반복문 사용)
        found = False
        for i, existing_cookie in enumerate(self._collected_cookies):
            if (
                existing_cookie["name"] == name
                and existing_cookie["domain"] == domain
                and existing_cookie["path"] == path
            ):
                self._collected_cookies[i] = cookie_data
                found = True
                break
        if not found:
            self._collected_cookies.append(cookie_data)

        log.debug(f"Cookie collected/updated: {name} ({domain})")

        # 필수 로그인 쿠키 확인 (더 정확한 쿠키 이름 사용 권장)
        if name in [
            "SAPISID",
            "SID",
            "SSID",
            "HSID",
            "APISID",
            "__Secure-1PSID",
            "__Secure-3PSID",
        ]:
            log.info(f"Essential login cookie detected: {name}")
            self._has_essential_login_cookie = True
            # 로그인 쿠키 감지 시 잠시 후 on_load_finished 재확인 시도 (선택적)
            # self._start_login_check_timer(delay=1000)

    def on_load_finished(self, success):
        """웹뷰 페이지 로드가 완료될 때 호출되는 슬롯.

        현재 URL과 로그인 쿠키 존재 여부를 확인하여 다음 단계를 결정합니다.
        - Google 페이지 + 로그인 쿠키 감지: YouTube로 리디렉션 시도.
        - YouTube 페이지 + 로그인 쿠키 감지: 로그인 완료 처리 시도.

        Args:
            success (bool): 페이지 로드 성공 여부.
        """
        log.debug(f"Page load finished. Success: {success}")
        if not success:
            log.warning("Page load failed.")
            # 오류 처리 (예: 사용자 알림, 재시도 버튼 활성화 등)
            # self.label.setText("페이지 로드 실패. 인터넷 연결 확인 후 다시 시도하세요.")
            # self.login_error.emit("Page load failed")
            return

        current_url = self.webview.url().toString()
        log.debug(f"Current URL: {current_url}")
        log.debug(f"Has essential login cookie: {self._has_essential_login_cookie}")

        # 시나리오 1: Google 계정 페이지이고 로그인 쿠키 감지됨 -> YouTube로 리디렉션 시도
        if "accounts.google.com" in current_url and self._has_essential_login_cookie:
            if not self._redirect_to_youtube_attempted:
                log.info(
                    "Login detected on Google page. Redirecting to YouTube shortly..."
                )
                self._redirect_to_youtube_attempted = True
                self.label.setText("로그인 확인 중... YouTube로 이동합니다.")
                # 약간의 지연 후 리디렉션 (페이지 스크립트 실행 시간 확보)
                QTimer.singleShot(2500, self.redirect_to_youtube)
            else:
                log.debug("Already attempted redirection to YouTube.")
            return  # 다른 조건 확인 불필요

        # 시나리오 2: YouTube 페이지이고 로그인 쿠키 감지됨 -> 로그인 완료 처리
        if "youtube.com" in current_url and self._has_essential_login_cookie:
            log.info("YouTube page detected with login cookie. Completing login...")
            self.label.setText("로그인이 감지되었습니다. 쿠키 저장 중...")
            # 약간의 지연 후 완료 처리 (쿠키 동기화 시간 확보)
            QTimer.singleShot(2000, self.complete_login)
            return  # 다른 조건 확인 불필요

        # 그 외의 경우 (로그인 페이지 로딩 중, 다른 페이지 등)
        log.debug(
            "Not performing redirection or completing login based on current state."
        )
        # 필요 시 사용자에게 안내 메시지 업데이트
        # self.label.setText("Google 계정으로 계속 로그인해주세요...")

    def redirect_to_youtube(self):
        """웹뷰를 YouTube 홈페이지로 리디렉션합니다."""
        log.info("Redirecting to https://www.youtube.com")
        self.webview.setUrl(QUrl("https://www.youtube.com"))

    def _get_netscape_cookie_string(self) -> str | None:
        """수집된 쿠키 목록(_collected_cookies)을 Netscape 형식 문자열로 변환합니다.

        Returns:
            str | None: 변환된 Netscape 쿠키 문자열, 쿠키가 없으면 None.
        """
        log.debug("Generating Netscape cookie string...")
        if not self._collected_cookies:
            log.warning("No cookies collected to generate string.")
            return None

        # 헤더 추가
        cookie_lines = [
            "# Netscape HTTP Cookie File",
            "# https://curl.se/docs/http-cookies.html",
            "# This file was generated by LHCVideoDownloader. Do not edit.",
            "",
        ]

        # 쿠키 데이터 정렬 및 형식화
        sorted_cookies = sorted(
            self._collected_cookies, key=lambda c: (c["domain"], c["path"], c["name"])
        )
        for cookie in sorted_cookies:
            line = "\t".join(
                [
                    cookie["domain"],
                    cookie["flag"],
                    cookie["path"],
                    cookie["secure"],
                    str(cookie["expiration"]),  # 문자열로 변환
                    cookie["name"],
                    cookie["value"],
                ]
            )
            cookie_lines.append(line)

        log.debug(f"Generated Netscape cookie string ({len(cookie_lines)-4} cookies).")
        return "\n".join(cookie_lines)

    def complete_login(self):
        """로그인 완료 처리.

        필수 로그인 쿠키 존재 여부를 확인하고, 쿠키를 Netscape 문자열로 변환하여
        ConfigManager를 통해 저장합니다. 성공 시 login_completed 시그널을 발생시킵니다.
        """
        log.info("Attempting to complete login...")
        if not self._has_essential_login_cookie:
            log.warning(
                "complete_login called, but essential login cookie not detected."
            )
            # 오류 처리 또는 사용자 알림
            # self.login_error.emit("Login could not be confirmed.")
            # self.close()
            return

        # Netscape 문자열 생성
        cookie_string = self._get_netscape_cookie_string()

        if not cookie_string:
            log.error("Failed to generate cookie string. Cannot save cookies.")
            self.login_error.emit("쿠키 정보를 생성하지 못했습니다.")
            self.close()
            return

        # ConfigManager를 통해 사이트별 쿠키 저장 시도
        log.info("Saving YouTube cookies via ConfigManager...")
        save_successful = self.config_manager.save_cookies_for_site('youtube', cookie_string)

        if save_successful:
            log.info("Cookies saved successfully. Emitting login_completed signal.")
            self.login_completed.emit()
        else:
            log.error("Failed to save cookies via ConfigManager.")
            self.login_error.emit("쿠키 저장에 실패했습니다.")

        # 성공/실패 여부와 관계없이 창 닫기
        log.info("Closing YouTubeAuthWindow.")
        self.close()

    # 창이 닫힐 때 타이머 정리 (선택적이지만 권장)
    def closeEvent(self, event):
        """창 닫기 이벤트 처리. 웹뷰 리소스를 정리합니다."""
        log.debug("YouTubeAuthWindow close event triggered.")
        # if self._login_check_timer and self._login_check_timer.isActive():
        #     self._login_check_timer.stop()
        #     log.debug("Login check timer stopped.")
        # 웹뷰 정리 (메모리 누수 방지)
        if hasattr(self, "webview"):
            self.webview.stop()
            self.webview.deleteLater()
            log.debug("Webview stopped and scheduled for deletion.")
        super().closeEvent(event)
