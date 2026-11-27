import argparse
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
from PySide6.QtWidgets import QApplication
from src.ui.main_window import MainWindow
from src.utils.helpers import get_logs_dir

# Ensure src is in python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))


def setup_logging(debug=False):
    logs_dir = get_logs_dir()
    os.makedirs(logs_dir, exist_ok=True)
    app_log_path = os.path.join(logs_dir, "app.log")

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG if debug else logging.INFO)
    console_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        app_log_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.handlers.clear()
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    return app_log_path


def main():
    parser = argparse.ArgumentParser(description="LHC Video Downloader")
    parser.add_argument('--debug', action='store_true', help='Enable debug logging mode')
    args = parser.parse_args()

    app_log_path = setup_logging(debug=args.debug)

    logger = logging.getLogger("Main")
    logger.info(f"Log file: {app_log_path}")
    if args.debug:
        logger.debug("=== Debug Mode Enabled ===")
        logger.debug(f"Python: {sys.version}")
        logger.debug(f"Platform: {sys.platform}")

    print("Starting application...")
    try:
        app = QApplication(sys.argv)
        if args.debug:
            logger.debug("QApplication created.")

        window = MainWindow()
        if args.debug:
            logger.debug("MainWindow created.")

        window.show()
        if args.debug:
            logger.debug("Window shown.")

        exit_code = app.exec()
        if args.debug:
            logger.debug(f"App finished with code {exit_code}")
        sys.exit(exit_code)
    except Exception as e:
        logger.critical(f"CRITICAL ERROR: {e}", exc_info=True)
        input("Press Enter to exit...")


if __name__ == "__main__":
    main()
