import sys
import os
import argparse
import logging
from PySide6.QtWidgets import QApplication
from src.ui.main_window import MainWindow

# Ensure src is in python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def main():
    # Parse Arguments
    parser = argparse.ArgumentParser(description="LHC Video Downloader")
    parser.add_argument('--debug', action='store_true', help='Enable debug logging mode')
    args = parser.parse_args()

    # Logging Setup
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    logger = logging.getLogger("Main")
    if args.debug:
        logger.debug("=== Debug Mode Enabled ===")
        logger.debug(f"Python: {sys.version}")
        logger.debug(f"Platform: {sys.platform}")

    print("Starting application...")
    try:
        app = QApplication(sys.argv)
        if args.debug: logger.debug("QApplication created.")
        
        window = MainWindow()
        if args.debug: logger.debug("MainWindow created.")
        
        window.show()
        if args.debug: logger.debug("Window shown.")
        
        exit_code = app.exec()
        if args.debug: logger.debug(f"App finished with code {exit_code}")
        sys.exit(exit_code)
    except Exception as e:
        logger.critical(f"CRITICAL ERROR: {e}", exc_info=True)
        input("Press Enter to exit...")

if __name__ == "__main__":
    main()
