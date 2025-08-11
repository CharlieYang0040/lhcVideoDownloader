import os
import json
import logging  # logging 임포트 추가
import sys  # sys 임포트 추가 (for FFmpeg path)

from cryptography.fernet import Fernet, InvalidToken  # InvalidToken 추가
import base64

# 모듈 레벨 로거 설정
log = logging.getLogger(__name__)


class ConfigManagerError(Exception):
    """ConfigManager 관련 오류를 위한 사용자 정의 예외"""

    pass


# --- 기본 ydl 옵션 --- (변경 가능)
DEFAULT_YDL_OPTIONS = {
    "format": "bv*[ext=mp4]+ba*[ext=m4a]/b*[ext=mp4]/bestvideo+bestaudio/best",
    "merge_output_format": "mkv",
    "writethumbnail": True,
    "concurrent_fragment_downloads": 8,
    "verbose": False,  # 일반 로그는 표준 로깅 사용
    "quiet": False,
    "no_warnings": False,
    "ignoreerrors": False,
    "no_mtime": True,
    "force_overwrites": True,
    "postprocessors": [
        {"key": "FFmpegVideoConvertor", "preferedformat": "mp4"},
        {"key": "FFmpegMetadata", "add_metadata": True},
        # EmbedThumbnail은 writethumbnail=True 시 자동 추가됨
    ],
    "postprocessor_args": {
        "ffmpeg": ["-loglevel", "info"],
        "FFmpegVideoConvertor": [
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-colorspace", "bt709",
            "-color_primaries", "bt709",
            "-color_trc", "bt709",
            "-color_range", "limited",
            "-max_muxing_queue_size", "4096",
            "-thread_queue_size", "4096",
            "-threads", "16"
        ]
    },
    # 'external_downloader': None, # 예: 'aria2c'
    # 'external_downloader_args': None,
}

# 설정 파일 버전 (이 구조가 변경될 때마다 숫자를 올립니다)
SETTINGS_VERSION = 1

class ConfigManager:
    """애플리케이션 설정, 쿠키, 암호화 키, yt-dlp 옵션을 관리하는 클래스."""
    def __init__(self):
        """ConfigManager 초기화.

        애플리케이션 디렉토리 설정, FFmpeg 경로 탐색, 암호화 시스템 초기화,
        설정 파일 로드 및 기본 yt-dlp 옵션 설정을 수행합니다.
        """
        self.app_name = "LHCVideoDownloader"
        try:
            appdata_path = os.getenv("LOCALAPPDATA")
            if not appdata_path:
                # 환경 변수 없을 경우 대체 경로 (예: 사용자 홈 디렉토리)
                appdata_path = os.path.expanduser("~")
                log.warning(
                    f"LOCALAPPDATA 환경 변수를 찾을 수 없어 사용자 홈 디렉토리를 사용합니다: {appdata_path}"
                )
            self.app_dir = os.path.join(appdata_path, self.app_name)
        except Exception as e:
            log.exception("애플리케이션 디렉토리 경로 설정 중 예상치 못한 오류 발생")
            # 심각한 오류로 간주하고 진행 중단 또는 기본값 사용
            self.app_dir = "."  # 예: 현재 디렉토리 사용

        self.config_dir = os.path.join(self.app_dir, "config")
        self.cookies_dir = os.path.join(self.app_dir, "cookies")
        self.encryption_key_file = os.path.join(self.config_dir, "encryption.key")
        self.encrypted_cookie_file = os.path.join(self.cookies_dir, "session.cookies")

        # FFmpeg 경로 초기화
        self.ffmpeg_path = self._determine_ffmpeg_path()
        if not self.ffmpeg_path or not os.path.exists(self.ffmpeg_path):
            log.error(
                f"FFmpeg를 찾을 수 없습니다. 예상 경로: {self.ffmpeg_path or '경로 미설정'}"
            )
            # 여기서 앱을 종료할 수는 없으므로, 경로가 없음을 로깅하고 None 유지
            self.ffmpeg_path = None
        else:
            log.info(f"Using FFmpeg at: {self.ffmpeg_path}")

        try:
            self.setup_directories()
        except Exception as e:
            log.exception(f"설정/쿠키 디렉토리 생성 실패: {e}")
            # 디렉토리 생성 실패 시 기능 제한 또는 종료 알림 필요

        self.fernet = None  # 미리 None으로 초기화
        try:
            self.encryption_key = self.load_or_create_encryption_key()
            if self.encryption_key:
                self.fernet = Fernet(self.encryption_key)
                log.info("암호화 시스템 초기화 완료.")
            else:
                log.error(
                    "암호화 키를 로드하거나 생성할 수 없어 암호화 기능이 비활성화됩니다."
                )
                # 사용자에게 알림 고려 (예: 상태 표시줄 메시지)
        except InvalidToken:
            log.error(
                "암호화 키 파일이 손상되었거나 유효하지 않습니다. 암호화 기능이 비활성화됩니다."
            )
            # 손상된 키 파일 처리 (예: 삭제 후 재생성 유도)
            # self._handle_corrupted_key()
        except (IOError, OSError) as e:
            log.exception(
                f"암호화 키 파일 처리 중 오류 발생: {e}. 암호화 기능이 비활성화됩니다."
            )
        except Exception as e:
            log.exception(
                f"암호화 시스템 초기화 중 예상치 못한 오류: {e}. 암호화 기능이 비활성화됩니다."
            )

        # 설정 파일 로드 및 버전 관리
        self._settings = self.load_all_settings()
        self._check_and_update_settings()

    def _check_and_update_settings(self):
        """설정 파일의 버전을 확인하고 필요한 경우 업데이트합니다."""
        current_version = self._settings.get("settings_version")
        
        if current_version != SETTINGS_VERSION:
            log.info(f"설정 파일 버전이 다르거나(현재: {current_version}, 최신: {SETTINGS_VERSION}) 없습니다. 업데이트를 시작합니다.")
            
            # 이전 설정에서 유지할 값들을 백업합니다.
            save_path = self._settings.get("save_path")
            
            # 기본 설정으로 초기화 (ydl_options 포함)
            new_settings = {"ydl_options": DEFAULT_YDL_OPTIONS.copy()}

            # 백업한 값을 새 설정에 복원합니다.
            if save_path:
                new_settings["save_path"] = save_path
                
            # 버전 정보를 추가하고 전체 설정을 저장합니다.
            new_settings["settings_version"] = SETTINGS_VERSION
            self.save_all_settings(new_settings)
            
            # 현재 인스턴스의 _settings도 갱신합니다.
            self._settings = new_settings
            log.info("설정 파일 업데이트 완료.")
        else:
            # 버전이 동일할 때, ydl_options가 없는 경우에만 기본값 추가 (최초 실행)
            if "ydl_options" not in self._settings:
                log.info("yt-dlp 기본 옵션을 설정 파일에 저장합니다.")
                self.save_setting("ydl_options", DEFAULT_YDL_OPTIONS)

    def _determine_ffmpeg_path(self):
        """FFmpeg 실행 파일 경로를 결정합니다.

        PyInstaller 빌드 환경과 일반 스크립트 실행 환경을 구분하여 탐색합니다.

        Returns:
            str | None: 찾은 FFmpeg 경로 또는 찾지 못한 경우 None.
        """
        # PyInstaller 빌드 환경 체크
        if getattr(sys, "frozen", False):
            # 빌드된 실행 파일의 경로
            base_path = getattr(sys, "_MEIPASS", os.path.abspath("."))
            # 상대 경로로 ffmpeg.exe 찾기 (빌드 구조에 따라 조정 필요)
            # 예: libs/ffmpeg/bin/ffmpeg.exe
            ffmpeg_path = os.path.join(base_path, "libs", "ffmpeg", "bin", "ffmpeg.exe")
        else:
            # 개발 환경 (스크립트 실행)
            # config_manager.py 파일의 위치를 기준으로 상대 경로 설정
            script_dir = os.path.dirname(os.path.abspath(__file__))
            # 프로젝트 루트는 script_dir의 상위 디렉토리
            project_root = os.path.abspath(os.path.join(script_dir, '..'))
            ffmpeg_path = os.path.join(project_root, "libs", "ffmpeg", "bin", "ffmpeg.exe")

        log.debug(f"Determined FFmpeg path: {ffmpeg_path}")
        # 최종 경로 존재 여부 확인 후 반환 (선택적이지만 더 안전)
        if os.path.exists(ffmpeg_path):
            return ffmpeg_path
        else:
            log.warning(f"Calculated FFmpeg path does not exist: {ffmpeg_path}")
            return None

    def setup_directories(self):
        """설정 및 쿠키 저장을 위한 디렉토리를 생성합니다."""
        try:
            os.makedirs(self.config_dir, exist_ok=True)
            os.makedirs(self.cookies_dir, exist_ok=True)
            log.info(
                f"Ensured directories exist: {self.config_dir}, {self.cookies_dir}"
            )
        except OSError as e:
            log.error(f"디렉토리 생성 중 오류 발생: {e}")
            raise ConfigManagerError(f"Failed to create directories: {e}") from e

    def load_or_create_encryption_key(self):
        """암호화 키 파일을 로드하거나, 없으면 새로 생성합니다.

        Returns:
            bytes | None: 로드 또는 생성된 암호화 키, 실패 시 None.
        """
        try:
            if os.path.exists(self.encryption_key_file):
                with open(self.encryption_key_file, "rb") as f:
                    key = f.read()
                # 키 유효성 검사 강화
                if not key or len(base64.urlsafe_b64decode(key)) != 32:
                    log.error(
                        f"암호화 키 파일이 유효하지 않습니다 (길이 오류 또는 빈 파일): {self.encryption_key_file}"
                    )
                    # 손상된 파일 처리 또는 None 반환
                    # os.remove(self.encryption_key_file) # 예: 손상된 파일 삭제
                    return None
                log.info(f"암호화 키 로드 완료: {self.encryption_key_file}")
                return key
            else:
                log.info("암호화 키 파일이 없어 새로 생성합니다...")
                key = Fernet.generate_key()
                # 키 저장 전 디렉토리 확인
                os.makedirs(os.path.dirname(self.encryption_key_file), exist_ok=True)
                with open(self.encryption_key_file, "wb") as f:
                    f.write(key)
                log.info(f"새 암호화 키 저장 완료: {self.encryption_key_file}")
                return key
        except (IOError, OSError) as e:
            log.exception(f"암호화 키 로드/생성 중 파일 오류 발생: {e}")
            return None
        except (ValueError, TypeError) as e:
            log.exception(f"암호화 키 데이터 형식 오류 (Base64 디코딩 등): {e}")
            return None

    def save_cookies(self, netscape_cookie_string):
        """Netscape 형식의 쿠키 문자열을 암호화하여 파일에 저장합니다.

        Args:
            netscape_cookie_string (str): 저장할 Netscape 형식 쿠키 문자열.

        Returns:
            bool: 저장 성공 여부.
        """
        if not self.fernet:
            log.error("암호화 시스템이 초기화되지 않아 쿠키를 저장할 수 없습니다.")
            return False  # 실패 반환
        try:
            # 기존 쿠키와 병합 후 저장
            merged_cookie_string = self._merge_cookies_with_existing(netscape_cookie_string)

            encrypted_data = self.fernet.encrypt(merged_cookie_string.encode("utf-8"))
            # 저장 전 디렉토리 확인
            os.makedirs(os.path.dirname(self.encrypted_cookie_file), exist_ok=True)
            with open(self.encrypted_cookie_file, "wb") as f:
                f.write(encrypted_data)
            log.info(f"암호화된 쿠키 저장 완료(병합): {self.encrypted_cookie_file}")
            return True  # 성공 반환
        except (IOError, OSError) as e:
            log.exception(f"쿠키 파일 쓰기 중 오류 발생: {e}")
        except Exception as e:
            log.exception(f"쿠키 암호화 또는 저장 중 예상치 못한 오류 발생: {e}")
        return False  # 실패 반환

    # --- Netscape 쿠키 포맷 유틸 ---
    def _parse_netscape_cookie_string(self, cookie_str: str) -> list:
        """Netscape 쿠키 문자열을 파싱하여 쿠키 딕셔너리 리스트로 반환합니다.

        각 쿠키는 dict(domain, flag, path, secure, expiration, name, value) 형태.
        잘못된 라인은 무시합니다.
        """
        if not cookie_str:
            return []
        cookies: list[dict] = []
        for raw_line in cookie_str.splitlines():
            line = raw_line.strip("\r\n")
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) != 7:
                # 탭 수가 맞지 않으면 스페이스로 구분되어 있을 가능성 고려
                parts = line.split()
            if len(parts) != 7:
                continue
            domain, flag, path, secure, expiration, name, value = parts
            cookies.append({
                "domain": domain,
                "flag": flag,
                "path": path,
                "secure": secure,
                "expiration": expiration,
                "name": name,
                "value": value,
            })
        return cookies

    def _serialize_netscape_cookies(self, cookies: list[dict]) -> str:
        """쿠키 딕셔너리 리스트를 Netscape 포맷 문자열로 직렬화합니다."""
        header = [
            "# Netscape HTTP Cookie File",
            "# https://curl.se/docs/http-cookies.html",
            "# This file was generated by LHCVideoDownloader. Do not edit.",
            "",
        ]
        # 정렬: 도메인, 경로, 이름
        sorted_items = sorted(
            cookies,
            key=lambda c: (c.get("domain", ""), c.get("path", ""), c.get("name", "")),
        )
        lines = []
        for c in sorted_items:
            try:
                lines.append("\t".join([
                    c.get("domain", ""),
                    c.get("flag", "FALSE"),
                    c.get("path", "/"),
                    c.get("secure", "FALSE"),
                    str(c.get("expiration", 0)),
                    c.get("name", ""),
                    c.get("value", ""),
                ]))
            except Exception:
                # 잘못된 쿠키는 건너뜀
                continue
        return "\n".join(header + lines)

    def _merge_cookies_with_existing(self, new_cookie_str: str) -> str:
        """기존 저장된 쿠키와 새로운 쿠키 문자열을 병합하여 반환합니다."""
        try:
            existing = self.load_cookies() or ""
        except Exception:
            existing = ""
        existing_list = self._parse_netscape_cookie_string(existing)
        new_list = self._parse_netscape_cookie_string(new_cookie_str)

        # 키: (domain, path, name)
        merged: dict[tuple, dict] = {}
        for c in existing_list:
            key = (c.get("domain", ""), c.get("path", ""), c.get("name", ""))
            merged[key] = c
        for c in new_list:
            key = (c.get("domain", ""), c.get("path", ""), c.get("name", ""))
            merged[key] = c  # 새 쿠키가 동일 키를 덮어씀

        return self._serialize_netscape_cookies(list(merged.values()))

    def load_cookies(self):
        """암호화된 쿠키 파일을 로드하고 복호화하여 Netscape 문자열로 반환합니다.

        Returns:
            str | None: 복호화된 Netscape 쿠키 문자열, 실패 시 None.
        """
        if not self.fernet:
            log.warning("암호화 시스템이 초기화되지 않아 쿠키를 로드할 수 없습니다.")
            return None
        if not os.path.exists(self.encrypted_cookie_file):
            log.info(f"암호화된 쿠키 파일 없음: {self.encrypted_cookie_file}")
            return None

        try:
            with open(self.encrypted_cookie_file, "rb") as f:
                encrypted_data = f.read()
            if not encrypted_data:
                log.warning(
                    f"암호화된 쿠키 파일이 비어 있습니다: {self.encrypted_cookie_file}"
                )
                return None

            decrypted_data = self.fernet.decrypt(encrypted_data)
            log.info("쿠키 로드 및 복호화 성공")
            return decrypted_data.decode("utf-8")
        except InvalidToken:
            log.error(
                f"쿠키 복호화 실패 (잘못된 키 또는 데이터 손상): {self.encrypted_cookie_file}. 이전 쿠키는 삭제됩니다."
            )
            # 복호화 실패 시, 사용자가 다시 로그인하도록 유도하기 위해 기존 파일 삭제
            self.delete_cookies()  # 자동 삭제
            return None
        except (IOError, OSError) as e:
            log.exception(f"쿠키 파일 읽기 오류 발생: {e}")
            return None
        except Exception as e:
            log.exception(f"쿠키 로드 또는 복호화 중 예상치 못한 오류 발생: {e}")
            return None

    def delete_cookies(self):
        """저장된 암호화된 쿠키 파일을 삭제합니다.

        Returns:
            bool: 삭제 성공 여부 (파일이 없어도 True 반환).
        """
        try:
            if os.path.exists(self.encrypted_cookie_file):
                os.remove(self.encrypted_cookie_file)
                log.info(f"암호화된 쿠키 파일 삭제 완료: {self.encrypted_cookie_file}")
                return True
            else:
                log.info("삭제할 쿠키 파일이 이미 존재하지 않습니다.")
                return True  # 이미 없어도 성공으로 간주
        except (IOError, OSError) as e:
            log.exception(f"쿠키 파일 삭제 중 오류 발생: {e}")
            return False

    # --- 설정 저장/로드 메서드 --- (오류 처리 강화)
    def get_settings_file_path(self):
        """설정 파일(app_settings.json)의 전체 경로를 반환합니다."""
        return os.path.join(self.config_dir, "app_settings.json")

    def load_all_settings(self):
        """JSON 설정 파일을 로드하여 파이썬 딕셔너리로 반환합니다 (내부 사용).

        파일이 없거나 오류 발생 시 빈 딕셔너리를 반환합니다.

        Returns:
            dict: 로드된 설정.
        """
        config_path = self.get_settings_file_path()
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    settings = json.load(f)
                    log.debug(f"설정 파일 로드 완료: {config_path}")
                    return (
                        settings if isinstance(settings, dict) else {}
                    )  # 로드된 데이터가 dict인지 확인
            except json.JSONDecodeError as e:
                log.error(f"설정 파일 JSON 디코딩 오류: {config_path} - {e}")
                # 손상된 설정 파일 처리 (백업, 삭제 등 고려)
                return {}  # 빈 딕셔너리 반환
            except (IOError, OSError) as e:
                log.exception(f"설정 파일 읽기 오류: {config_path} - {e}")
                return {}
            except Exception as e:
                log.exception(
                    f"설정 파일 로드 중 예상치 못한 오류: {config_path} - {e}"
                )
                return {}
        else:
            log.info(f"설정 파일 없음, 기본값 사용: {config_path}")
            return {}  # 파일 없을 시 빈 딕셔너리 반환

    def save_setting(self, key, value):
        """특정 설정을 내부 _settings 딕셔너리에 업데이트하고 전체 설정을 JSON 파일에 저장합니다.

        Args:
            key (str): 저장할 설정의 키.
            value (any): 저장할 설정의 값 (JSON 직렬화 가능해야 함).

        Returns:
            bool: 저장 성공 여부.
        """
        self._settings[key] = value  # 내부 _settings 업데이트
        config_path = self.get_settings_file_path()
        try:
            # 설정 디렉토리가 없는 경우 생성 (setup_directories에서 이미 시도했어야 함)
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(
                    self._settings, f, indent=4, ensure_ascii=False
                )  # ensure_ascii=False 추가 (한글 등)
            log.info(f"설정 저장: {key} = {value} in {config_path}")
            return True
        except (IOError, OSError) as e:
            log.exception(f"설정 파일 쓰기 오류: {config_path} - {e}")
        except TypeError as e:
            log.exception(
                f"설정 저장 실패 (JSON 직렬화 불가 데이터 타입): key={key}, type={type(value)} - {e}"
            )
        except Exception as e:
            log.exception(f"설정 저장 중 예상치 못한 오류: {config_path} - {e}")
        return False

    def load_setting(self, key, default=None):
        """내부 _settings 딕셔너리에서 특정 설정 값을 로드합니다.

        Args:
            key (str): 로드할 설정의 키.
            default (any, optional): 키가 없을 경우 반환할 기본값. Defaults to None.

        Returns:
            any: 로드된 설정 값 또는 기본값.
        """
        value = self._settings.get(key, default)
        log.debug(f"설정 로드: {key} = {value} (default: {default})")
        return value

    # --- 설정 저장/로드 메서드 끝 ---

    # --- yt-dlp 옵션 관련 메서드 ---
    def get_ydl_options(self):
        """저장된 yt-dlp 옵션을 반환합니다 (설정값의 복사본).

        설정 파일에 옵션이 없으면 기본값(DEFAULT_YDL_OPTIONS)을 사용합니다.

        Returns:
            dict: yt-dlp 옵션 딕셔너리.
        """
        # 설정 파일에서 로드된 옵션 사용, 없으면 기본값
        # 내부 _settings 에서 깊은 복사하여 반환 (원본 수정 방지)
        import copy

        options = self._settings.get("ydl_options", DEFAULT_YDL_OPTIONS)
        return copy.deepcopy(options)

    def save_ydl_options(self, options: dict):
        """yt-dlp 옵션을 설정 파일에 저장합니다.

        Args:
            options (dict): 저장할 yt-dlp 옵션 딕셔너리.

        Returns:
            bool: 저장 성공 여부.
        """
        # 기본 옵션과 병합하거나, 받은 옵션만 저장할 수 있음
        # 여기서는 받은 옵션으로 덮어쓰기
        log.info("yt-dlp 옵션을 설정 파일에 저장합니다.")
        return self.save_setting("ydl_options", options)

    def save_all_settings(self, settings_dict):
        """전체 설정 객체를 JSON 파일에 저장합니다.

        Args:
            settings_dict (dict): 저장할 전체 설정 딕셔너리.
        """
        path = self.get_settings_file_path()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(settings_dict, f, indent=4, ensure_ascii=False)
            log.debug(f"전체 설정 저장 완료: {path}")
        except (IOError, OSError) as e:
            log.error(f"설정 파일 쓰기 오류: {e}")
            raise ConfigManagerError(f"Failed to write settings file: {e}") from e
