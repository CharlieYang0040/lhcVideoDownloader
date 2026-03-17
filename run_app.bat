@echo off
cd /d "%~dp0"

if not exist "venv\Scripts\activate.bat" (
    echo Creating virtual environment...
    python -m venv venv
)

call venv\Scripts\activate.bat

echo Installing/Updating dependencies...
python -m pip install --upgrade pip
pip install -r requirements.txt

echo Checking for external binaries (yt-dlp, ffmpeg)...
python setup_binaries.py


echo Starting LHC Video Downloader...
python -m src.main %*
pause
