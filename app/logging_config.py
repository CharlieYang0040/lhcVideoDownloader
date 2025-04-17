import logging
import logging.handlers
import os
import sys

LOG_DIR_NAME = "logs"
LOG_FILE_NAME = "app.log"
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 3


def setup_logging(log_level=logging.DEBUG):
    """애플리케이션 로깅 시스템을 설정합니다."""

    # 애플리케이션 디렉토리 결정
    if getattr(sys, "frozen", False):
        # PyInstaller 등으로 빌드된 경우
        app_dir = os.path.dirname(sys.executable)
    else:
        # 일반 실행의 경우 (main 스크립트 기준)
        # 이 함수가 호출되는 위치에 따라 경로 조정이 필요할 수 있음
        # videoDownloaderApp.py 에서 호출될 것을 가정
        app_dir = os.path.dirname(
            os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        )
        # 만약 main 스크립트와 같은 디렉토리에 있다면 아래 사용
        # app_dir = os.path.dirname(os.path.abspath(__file__))

    log_dir = os.path.join(app_dir, LOG_DIR_NAME)
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError as e:
        print(f"Error creating log directory {log_dir}: {e}")
        # 로그 디렉토리 생성 실패 시 콘솔 로깅만 사용하거나 종료
        return

    log_file = os.path.join(log_dir, LOG_FILE_NAME)

    # 루트 로거 가져오기
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)  # 모든 핸들러에 대한 기본 레벨 설정

    # 포매터 생성
    log_formatter = logging.Formatter(LOG_FORMAT)

    # 기존 핸들러 제거 (중복 방지) - 필요에 따라 선택
    # for handler in root_logger.handlers[:]:
    #     root_logger.removeHandler(handler)

    # 파일 핸들러 설정 (RotatingFileHandler)
    # 파일 핸들러 중복 추가 방지
    if not any(
        isinstance(h, logging.handlers.RotatingFileHandler)
        and h.baseFilename == log_file
        for h in root_logger.handlers
    ):
        try:
            file_handler = logging.handlers.RotatingFileHandler(
                log_file, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
            )
            file_handler.setFormatter(log_formatter)
            file_handler.setLevel(log_level)  # 파일 핸들러 레벨 설정
            root_logger.addHandler(file_handler)
            print(f"Logging to file: {log_file}")
        except Exception as e:
            print(f"Error setting up file handler for {log_file}: {e}")
    else:
        print(f"File handler for {log_file} already exists.")

    # 콘솔 핸들러 설정 (선택 사항)
    if not any(isinstance(h, logging.StreamHandler) for h in root_logger.handlers):
        try:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(log_formatter)
            # 콘솔에는 INFO 레벨 이상만 출력하도록 설정 가능
            console_handler.setLevel(logging.INFO)
            root_logger.addHandler(console_handler)
            print("Logging to console enabled.")
        except Exception as e:
            print(f"Error setting up console handler: {e}")

    logging.info("--- Logging System Initialized ---")
    logging.info(f"Application directory: {app_dir}")
    logging.info(f"Log file path: {log_file}")
    # 초기화 완료 후 테스트 로그
    logging.debug("Debug level log test.")
    logging.info("Info level log test.")
    logging.warning("Warning level log test.")
    logging.error("Error level log test.")
    logging.critical("Critical level log test.")
