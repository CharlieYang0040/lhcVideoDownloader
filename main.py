import sys
import logging
from PySide6.QtWidgets import QApplication

# app 폴더 내 모듈 임포트
from app.videoDownloaderApp import VideoDownloaderApp
from app.logging_config import setup_logging

if __name__ == "__main__":
    # 로깅 설정 먼저 호출
    setup_logging()
    # QApplication 인스턴스 생성
    app = QApplication(sys.argv)
    try:
        # 메인 윈도우 인스턴스 생성 및 표시
        window = VideoDownloaderApp()
        window.show()
        # 애플리케이션 실행 루프 시작
        sys.exit(app.exec())
    except SystemExit:
        # sys.exit() 호출 시 정상 종료 처리
        pass
    except Exception as e:
        # 초기화 또는 실행 중 예외 발생 시 로깅 및 종료
        logging.critical(f"Application failed: {e}", exc_info=True)
        # 사용자에게 오류 메시지를 보여주는 GUI 방식도 고려 가능
        print(f"CRITICAL ERROR: Application failed to start or run - {e}")
        sys.exit(1)
