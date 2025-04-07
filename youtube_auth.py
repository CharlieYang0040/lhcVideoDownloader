from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLabel, QMessageBox
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineCookieStore, QWebEngineProfile
from PySide6.QtCore import QUrl, Signal, Qt, QTimer
import os
import tempfile
import time
from config_manager import ConfigManager
import logging

class YouTubeAuthWindow(QWidget):
    login_completed = Signal()
    login_error = Signal(str)

    def __init__(self):
        super().__init__()
        print("[AuthWindow] __init__ 시작")

        self.config_manager = ConfigManager()

        print("[AuthWindow] 로그인 UI 초기화 시작...")
        self.setWindowTitle("YouTube 로그인")
        self.setGeometry(100, 100, 800, 600)

        layout = QVBoxLayout()

        self.label = QLabel("Google 계정으로 로그인해주세요")
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label)

        try:
            print("[AuthWindow] QWebEngineView 생성 시도...")
            self.webview = QWebEngineView()
            print("[AuthWindow] QWebEngineView 생성 완료.")
            self.webview.setUrl(QUrl("https://accounts.google.com/signin/v2/identifier?service=youtube"))
            print("[AuthWindow] Google 로그인 URL 로드 시도...")

            # 쿠키 스토어 설정 및 연결
            self.cookie_store = self.webview.page().profile().cookieStore()
            self.cookie_store.cookieAdded.connect(self.on_cookie_added)

            layout.addWidget(self.webview)
            self.setLayout(layout)

            # 내부 상태 변수 초기화
            self.cookies = []
            self.login_check_count = 0
            self.webview.loadFinished.connect(self.on_load_finished)
            self.redirect_attempted = False
            self.has_login_cookie = False

            print("[AuthWindow] 로그인 UI 초기화 완료.")
            self.show()
            print("[AuthWindow] 로그인 창 표시됨 (show 호출됨)")

        except Exception as e:
            # 웹뷰 생성/로드 실패 시
            error_msg = f"[AuthWindow] 로그인 웹뷰 생성/로드 중 오류: {e}"
            print(error_msg)
            # 사용자에게 알림 표시
            QMessageBox.critical(self, "오류", f"""로그인 창을 여는 중 오류가 발생했습니다:
{e}

QtWebEngine 관련 구성 요소를 확인하세요.""")
            # 오류 발생 시 창 즉시 닫기 (이미 show()가 호출되지 않았을 수 있음)
            QTimer.singleShot(0, self.close)

    def on_cookie_added(self, cookie):
        """쿠키가 추가될 때마다 호출되는 메서드 (로그인 상태 확인 및 수집)"""
        if any(domain in cookie.domain() for domain in ['.youtube.com', '.google.com']):
            name = cookie.name().data().decode()
            value = cookie.value().data().decode()
            domain = cookie.domain()
            path = cookie.path()
            secure = cookie.isSecure()
            http_only = cookie.isHttpOnly() # Netscape 형식은 HttpOnly 플래그 없음
            expires = cookie.expirationDate().toSecsSinceEpoch() if not cookie.isSessionCookie() else 0 # 세션 쿠키는 0

            # Netscape 형식에 필요한 데이터 저장 (도메인, 경로, 보안, 만료, 이름, 값)
            cookie_data = {
                'domain': domain,
                'flag': 'TRUE' if domain.startswith('.') else 'FALSE', # hostOnly 플래그
                'path': path,
                'secure': 'TRUE' if secure else 'FALSE',
                'expiration': int(expires),
                'name': name,
                'value': value
            }

            # 중복 쿠키 제거 (동일 이름, 도메인, 경로)
            self.cookies = [c for c in self.cookies 
                            if not (c['name'] == name and c['domain'] == domain and c['path'] == path)]
            self.cookies.append(cookie_data)
            print(f"[AuthWindow] 쿠키 수집: {name} ({domain})")
            
            # 로그인 상태 확인용 플래그 설정
            if name in ['SAPISID', 'SID', '__Secure-1PSID']:
                self.has_login_cookie = True
                print(f"[AuthWindow] 로그인 관련 쿠키 감지: {name}")

    def on_load_finished(self, success):
        logging.debug(f"[AuthWindow] on_load_finished called. Success: {success}")
        if not success:
            logging.warning("[AuthWindow] Page load failed.")
            return

        current_url = self.webview.url().toString()
        logging.debug(f"[AuthWindow] Current URL: {current_url}")
        logging.debug(f"[AuthWindow] has_login_cookie: {self.has_login_cookie}")
        
        if "myaccount.google.com" in current_url and self.has_login_cookie:
            if not self.redirect_attempted:
                self.redirect_attempted = True
                self.label.setText("로그인 확인 중... YouTube로 이동합니다.")
                QTimer.singleShot(2000, self.redirect_to_youtube)
                
        elif "youtube.com" in current_url and self.has_login_cookie:
            logging.info("[AuthWindow] YouTube URL detected with login cookie. Scheduling complete_login...")
            self.label.setText("로그인이 완료되었습니다. 잠시만 기다려주세요...")
            QTimer.singleShot(2000, self.complete_login)
        else:
            logging.debug("[AuthWindow] Not redirecting or completing login based on current URL/cookie state.")

    def redirect_to_youtube(self):
        self.webview.setUrl(QUrl("https://www.youtube.com"))

    def save_cookies_to_config_manager(self):
        """수집된 쿠키를 Netscape 형식 문자열로 변환하여 ConfigManager에 저장"""
        logging.debug("[AuthWindow] save_cookies_to_config_manager started.")
        if not self.cookies:
            logging.warning("[AuthWindow] No cookies collected to save.")
            return
            
        # Netscape 형식 문자열 생성
        cookie_content = "# Netscape HTTP Cookie File\n"
        cookie_content += "# https://curl.haxx.se/rfc/cookie_spec.html\n"
        cookie_content += "# This is a generated file! Do not edit.\n\n"
        
        # 쿠키 정렬 (선택적, 가독성 향상)
        sorted_cookies = sorted(self.cookies, key=lambda c: (c['domain'], c['path'], c['name']))

        for cookie in sorted_cookies:
            # 도메인 앞에 .이 없으면 hostOnly=TRUE (Netscape은 반대)
            # flag = 'TRUE' if cookie['domain'].startswith('.') else 'FALSE' -> flag 키 추가함
            
            # Netscape 형식: domain<TAB>flag<TAB>path<TAB>secure<TAB>expiration<TAB>name<TAB>value
            cookie_content += f"{cookie['domain']}\t"
            cookie_content += f"{cookie['flag']}\t"
            cookie_content += f"{cookie['path']}\t"
            cookie_content += f"{cookie['secure']}\t"
            cookie_content += f"{cookie['expiration']}\t"
            cookie_content += f"{cookie['name']}\t"
            cookie_content += f"{cookie['value']}\n"
        
        logging.debug(f"[AuthWindow] Generated Netscape cookie string (first 100 chars): {cookie_content[:100]}")

        # ConfigManager를 통해 암호화 및 저장
        try:
            logging.debug("[AuthWindow] Calling config_manager.save_cookies...")
            self.config_manager.save_cookies(cookie_content)
            logging.info("[AuthWindow] ConfigManager save_cookies call successful.")
        except Exception as e:
             logging.exception("[AuthWindow] Error during config_manager.save_cookies call")

    def complete_login(self):
        logging.debug("[AuthWindow] complete_login started.")
        if self.has_login_cookie:
            logging.info("[AuthWindow] Login confirmed (has_login_cookie is True). Attempting to save cookies...")
            # 쿠키 저장 로직 호출
            self.save_cookies_to_config_manager()
            logging.info("[AuthWindow] Cookie saving process finished. Emitting login_completed signal...")
            self.login_completed.emit()
            logging.info("[AuthWindow] login_completed signal emitted. Closing window.")
            self.close()
        else:
            logging.warning("[AuthWindow] complete_login called, but has_login_cookie is False.")