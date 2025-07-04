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

    # main.py 가 있는 프로젝트 루트 디렉토리를 기준으로 경로 설정
    # __main__ 모듈의 파일 경로를 사용하여 프로젝트 루트를 찾음
    try:
        if getattr(sys, "frozen", False):
            # PyInstaller 등으로 빌드된 경우, 실행 파일이 있는 디렉토리
            project_root = os.path.dirname(sys.executable)
        else:
            # 일반 실행의 경우, main.py의 디렉토리
            # sys.modules['__main__'] 은 엔트리포인트 스크립트를 가리킴
            main_py_path = sys.modules['__main__'].__file__
            project_root = os.path.dirname(os.path.abspath(main_py_path))
    except (KeyError, AttributeError):
        # 안전 장치: __main__ 모듈을 찾을 수 없을 경우 CWD 기준
        project_root = os.getcwd()


    log_dir = os.path.join(project_root, LOG_DIR_NAME)
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
    logging.info(f"Application directory: {project_root}")
    logging.info(f"Log file path: {log_file}")
    # 초기화 완료 후 테스트 로그
    logging.debug("Debug level log test.")
    logging.info("Info level log test.")
    logging.warning("Warning level log test.")
    logging.error("Error level log test.")
    logging.critical("Critical level log test.")
