import os
import json
from pathlib import Path
# cryptography 관련 임포트 복구
from cryptography.fernet import Fernet
import base64

class ConfigManager:
    def __init__(self):
        # 애플리케이션 기본 디렉토리 설정
        self.app_name = "LHCVideoDownloader"
        self.app_dir = os.path.join(os.getenv('LOCALAPPDATA'), self.app_name)
        self.config_dir = os.path.join(self.app_dir, "config")
        # 쿠키 디렉토리 변수 복구
        self.cookies_dir = os.path.join(self.app_dir, "cookies")
        self.encryption_key_file = os.path.join(self.config_dir, "encryption.key")
        # 암호화된 쿠키 파일 경로
        self.encrypted_cookie_file = os.path.join(self.cookies_dir, "session.cookies")
        
        # 디렉토리 생성 (config 및 cookies)
        self.setup_directories()
        
        # 암호화 키 초기화 복구
        try:
            self.encryption_key = self.load_or_create_encryption_key()
            self.fernet = Fernet(self.encryption_key)
        except Exception as e:
            print(f"[ConfigManager] 암호화 설정 중 오류: {e}")
            # 오류 발생 시 암호화 비활성화 또는 앱 종료 고려
            self.fernet = None 

    def setup_directories(self):
        """필요한 디렉토리 구조 생성"""
        os.makedirs(self.config_dir, exist_ok=True)
        # 쿠키 디렉토리 생성 복구
        os.makedirs(self.cookies_dir, exist_ok=True)

    # 암호화 키 로드/생성 메서드 복구
    def load_or_create_encryption_key(self):
        """암호화 키 로드 또는 생성"""
        if os.path.exists(self.encryption_key_file):
            with open(self.encryption_key_file, 'rb') as f:
                key = f.read()
                # 키 유효성 검사 (길이 등)
                if len(base64.urlsafe_b64decode(key)) != 32:
                     raise ValueError("Invalid encryption key length")
                return key
        else:
            print("[ConfigManager] 암호화 키 생성 중...")
            key = Fernet.generate_key()
            with open(self.encryption_key_file, 'wb') as f:
                f.write(key)
            return key

    # 쿠키 저장 메서드 복구 (Netscape 문자열 직접 암호화)
    def save_cookies(self, netscape_cookie_string):
        """Netscape 형식의 쿠키 문자열을 암호화하여 저장"""
        if not self.fernet:
            print("[ConfigManager] 암호화가 초기화되지 않아 쿠키를 저장할 수 없습니다.")
            return
        try:
            # 문자열을 바이트로 인코딩 후 암호화
            encrypted_data = self.fernet.encrypt(netscape_cookie_string.encode('utf-8'))
            with open(self.encrypted_cookie_file, 'wb') as f:
                f.write(encrypted_data)
            print(f"[ConfigManager] 쿠키 저장 완료: {self.encrypted_cookie_file}")
        except Exception as e:
            print(f"[ConfigManager] 쿠키 저장 중 오류 발생: {e}")

    # 쿠키 로드 메서드 복구 (복호화 후 Netscape 문자열 반환)
    def load_cookies(self):
        """저장된 쿠키 데이터 로드 및 복호화하여 Netscape 문자열 반환"""
        if not self.fernet:
            print("[ConfigManager] 암호화가 초기화되지 않아 쿠키를 로드할 수 없습니다.")
            return None
        if not os.path.exists(self.encrypted_cookie_file):
            print(f"[ConfigManager] 쿠키 파일 없음: {self.encrypted_cookie_file}")
            return None
        
        try:
            with open(self.encrypted_cookie_file, 'rb') as f:
                encrypted_data = f.read()
            # 복호화 후 바이트를 문자열로 디코딩
            decrypted_data = self.fernet.decrypt(encrypted_data)
            print("[ConfigManager] 쿠키 로드 및 복호화 성공")
            return decrypted_data.decode('utf-8')
        except Exception as e:
            # 복호화 실패 (키 변경, 파일 손상 등) 시 기존 파일 삭제 고려
            print(f"[ConfigManager] 쿠키 로드/복호화 중 오류 발생: {e}. 기존 쿠키 파일일 수 있습니다.")
            # self.delete_cookies() # 오류 시 자동 삭제하려면 주석 해제
            return None

    # 쿠키 삭제 메서드 복구
    def delete_cookies(self):
        """저장된 암호화된 쿠키 삭제"""
        try:
            if os.path.exists(self.encrypted_cookie_file):
                os.remove(self.encrypted_cookie_file)
                print(f"[ConfigManager] 쿠키 파일 삭제 완료: {self.encrypted_cookie_file}")
            else:
                 print("[ConfigManager] 삭제할 쿠키 파일 없음")
        except Exception as e:
            print(f"[ConfigManager] 쿠키 파일 삭제 중 오류: {e}")

    # --- 설정 저장/로드 메서드 추가 ---
    def get_settings_file_path(self):
        """설정 파일 경로 반환"""
        return os.path.join(self.config_dir, 'app_settings.json')

    def load_all_settings(self):
        """JSON 설정 파일 로드"""
        config_path = self.get_settings_file_path()
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                print(f"[ConfigManager] 설정 파일 JSON 디코딩 오류: {config_path}")
                return {}
            except Exception as e:
                print(f"[ConfigManager] 설정 파일 로드 오류: {e}")
                return {}
        return {}

    def save_setting(self, key, value):
        """특정 설정을 JSON 파일에 저장"""
        settings = self.load_all_settings()
        settings[key] = value
        config_path = self.get_settings_file_path()
        try:
            # 설정 디렉토리가 없는 경우 생성
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=4)
            print(f"[ConfigManager] 설정 저장: {key} = {value} in {config_path}")
        except Exception as e:
            print(f"[ConfigManager] 설정 저장 오류: {e}")

    def load_setting(self, key, default=None):
        """특정 설정을 JSON 파일에서 로드"""
        settings = self.load_all_settings()
        value = settings.get(key, default)
        print(f"[ConfigManager] 설정 로드: {key} = {value} (default: {default})")
        return value
    # --- 설정 저장/로드 메서드 끝 ---
