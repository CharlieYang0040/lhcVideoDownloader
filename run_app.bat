@echo off
cd /d "%~dp0"

if not exist "venv\Scripts\activate.bat" (
    echo Creating virtual environment...
    python -m venv venv
    call venv\Scripts\activate.bat
    echo Installing runtime dependencies...
    python -m pip install -r requirements.txt
) else (
    call venv\Scripts\activate.bat
    python -c "import PySide6" 2>nul
    if errorlevel 1 (
        echo Installing missing runtime dependencies...
        python -m pip install -r requirements.txt
    )
)

echo Checking for external binaries (yt-dlp, ffmpeg, deno)...
python setup_binaries.py --no-ytdlp-update

echo Starting LHC Video Downloader...
python -m src.main %*
pause
