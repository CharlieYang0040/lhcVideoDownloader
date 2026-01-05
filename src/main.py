import sys
from PySide6.QtWidgets import QApplication
from src.ui.main_window import MainWindow

def main():
    print("Starting application...")
    try:
        app = QApplication(sys.argv)
        print("QApplication created.")
        
        window = MainWindow()
        print("MainWindow created.")
        window.show()
        print("Window shown.")
        
        exit_code = app.exec()
        print(f"App finished with code {exit_code}")
        sys.exit(exit_code)
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        input("Press Enter to exit...")

if __name__ == "__main__":
    main()
