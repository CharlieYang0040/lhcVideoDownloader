@echo off

chcp 65001
echo.

@REM Python 설치 확인
where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo Python이 설치되어 있지 않습니다.
    echo https://www.python.org/downloads/ 에서 Python을 설치해주세요.
    pause
    exit /b 1
)

set "VIRTUAL_ENV=%~dp0venv"

@REM venv 폴더 존재 확인
if not exist "%VIRTUAL_ENV%" (
    echo 가상환경을 생성합니다...
    python -m venv venv
    if %ERRORLEVEL% neq 0 (
        echo 가상환경 생성에 실패했습니다.
        pause
        exit /b 1
    )
    echo 가상환경이 생성되었습니다.
    echo.
)

@REM requirements.txt 파일 검사 및 패키지 설치
if exist "%~dp0\requirements.txt" (
    echo requirements.txt 파일을 찾았습니다. 필요한 패키지를 설치합니다...
    "%VIRTUAL_ENV%\Scripts\python.exe" -m pip install --upgrade pip
    "%VIRTUAL_ENV%\Scripts\pip" install -r "%~dp0\requirements.txt"
    if %ERRORLEVEL% neq 0 (
        echo 패키지 설치 중 오류가 발생했습니다.
        echo 필요한 패키지가 올바르게 설치되지 않았을 수 있습니다.
        pause
    ) else (
        echo 패키지 설치가 성공적으로 완료되었습니다.
    )
) else (
    echo 경고: requirements.txt 파일을 찾을 수 없습니다.
    echo 필요한 패키지가 설치되지 않을 수 있습니다.
)

echo.

@REM --- FFmpeg 설치 스크립트 실행 준비 및 실행 --- 
@REM FFmpeg 설치 스크립트 실행에 필요한 추가 패키지 설치
echo FFmpeg 설치 스크립트에 필요한 추가 패키지를 설치합니다 (requests, py7zr, tqdm)...
"%VIRTUAL_ENV%\Scripts\pip" install requests py7zr tqdm
if %ERRORLEVEL% neq 0 (
    echo FFmpeg 설치용 패키지 설치 중 오류가 발생했습니다.
    echo FFmpeg 자동 설치가 실패할 수 있습니다.
    pause
) else (
    echo FFmpeg 설치용 패키지 설치 완료.
)

echo.

echo FFmpeg 설치 상태를 확인하고 필요시 설치합니다...
if exist "%~dp0\install_ffmpeg_bin.py" (
    "%VIRTUAL_ENV%\Scripts\python.exe" "%~dp0\install_ffmpeg_bin.py"
    if %ERRORLEVEL% neq 0 (
        echo FFmpeg 설치/확인 중 오류가 발생했습니다.
        echo 앱 실행에 문제가 있을 수 있습니다.
        pause
    ) else (
        echo FFmpeg 준비 완료.
    )
) else (
    echo 경고: install_ffmpeg_bin.py 파일을 찾을 수 없습니다.
    echo FFmpeg 자동 설치를 건너뛰었습니다. libs 폴더에 수동으로 설치해야 할 수 있습니다.
)

echo.
@REM --- FFmpeg 설치 스크립트 실행 끝 --- 

set "PATH=%VIRTUAL_ENV%\Scripts;%PATH%"
set "PYTHONPATH=%VIRTUAL_ENV%\Lib\site-packages;%PYTHONPATH%"

echo 가상환경 경로: %VIRTUAL_ENV%
echo Python 인터프리터: "%VIRTUAL_ENV%\Scripts\python.exe"

@REM Python 인터프리터 존재 확인
if exist "%VIRTUAL_ENV%\Scripts\python.exe" (
    "%VIRTUAL_ENV%\Scripts\python.exe" -c "import sys; print('Python 버전:', sys.version)"
) else (
    echo 오류: Python 인터프리터를 찾을 수 없습니다.
    echo 경로: "%VIRTUAL_ENV%\Scripts\python.exe"
    pause
    exit /b 1
)

echo 가상환경이 활성화되었습니다.
echo.

@REM main.py 실행
if exist "%~dp0\videoDownloaderApp.py" (
    "%VIRTUAL_ENV%\Scripts\python.exe" "%~dp0\videoDownloaderApp.py"
) else (
    echo 오류: videoDownloaderApp.py 파일을 찾을 수 없습니다.
    pause
    exit /b 1
)

pause