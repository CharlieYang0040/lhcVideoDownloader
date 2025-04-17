import os
import sys
import requests
import shutil
import tempfile

# import subprocess # 7z.exe 호출 대신 zipfile 사용
import zipfile  # .zip 파일 처리를 위해 추가
from tqdm import tqdm  # 진행률 표시용 라이브러리
import logging

# 로깅 설정
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# --- 설정값 ---
FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"  # .zip 파일로 변경
# 압축 해제 후 예상되는 ffmpeg.exe의 상대 경로 (압축 파일 구조에 따라 달라질 수 있음)
# 예: ffmpeg-6.1-essentials_build/bin/ffmpeg.exe -> 첫번째 폴더 이름은 가변적일 수 있음
EXPECTED_FFMPEG_SUBPATH = os.path.join("bin", "ffmpeg.exe")

# 프로젝트 루트 디렉토리 기준 목표 경로 설정
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = (
    os.path.dirname(SCRIPT_DIR)
    if os.path.basename(SCRIPT_DIR) == "scripts"
    else SCRIPT_DIR
)  # 스크립트 위치에 따라 조정
TARGET_DIR = os.path.join(PROJECT_ROOT, "libs", "ffmpeg", "bin")
TARGET_FFMPEG_PATH = os.path.join(TARGET_DIR, "ffmpeg.exe")
# -------------


def download_file(url, destination):
    """주어진 URL에서 파일을 다운로드하고 지정된 경로에 저장"""
    logging.info(f"Downloading FFmpeg from: {url}")
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()  # 오류 발생 시 예외 발생

        total_size = int(response.headers.get("content-length", 0))
        block_size = 1024  # 1 KB

        # tqdm으로 다운로드 진행률 표시
        progress_bar = tqdm(total=total_size, unit="iB", unit_scale=True)
        with open(destination, "wb") as f:
            for data in response.iter_content(block_size):
                progress_bar.update(len(data))
                f.write(data)
        progress_bar.close()

        if total_size != 0 and progress_bar.n != total_size:
            logging.error("Download error: Size mismatch.")
            return False

        logging.info(f"FFmpeg archive downloaded successfully to: {destination}")
        return True
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to download FFmpeg: {e}")
        return False
    except Exception as e:
        logging.error(f"An error occurred during download: {e}")
        return False


def extract_ffmpeg(archive_path, extract_to_dir):
    """ZIP 아카이브에서 모든 파일을 지정된 디렉토리에 압축 해제 (내장 zipfile 사용)"""
    logging.info(
        f"Extracting ZIP archive: {archive_path} to {extract_to_dir} using zipfile"
    )
    try:
        with zipfile.ZipFile(archive_path, "r") as zip_ref:
            # 압축 해제 진행률 표시 (선택 사항)
            members = zip_ref.namelist()
            total_files = len(members)
            logging.info(f"Found {total_files} files in the archive.")
            # tqdm 같은 라이브러리로 상세 진행률 표시 가능하나, 여기서는 단순화
            # for member in tqdm(members, desc="Extracting files"):
            #     zip_ref.extract(member, extract_to_dir)
            zip_ref.extractall(extract_to_dir)
        logging.info("Extraction completed successfully.")
        return True
    except zipfile.BadZipFile:
        logging.error(
            f"Failed to extract archive: The file is not a zip file or it is corrupted."
        )
        return False
    except Exception as e:
        logging.error(f"An unexpected error occurred during extraction: {e}")
        return False


def find_and_move_ffmpeg(extract_dir, target_path):
    """압축 해제된 디렉토리에서 ffmpeg.exe를 찾아 목표 경로로 이동"""
    logging.info(f"Searching for ffmpeg.exe in {extract_dir}")
    ffmpeg_found = False
    source_ffmpeg_path = None

    # 압축 해제된 폴더 구조 내에서 ffmpeg.exe 검색
    # 보통 최상위 폴더 이름은 버전마다 다르므로 내부를 탐색
    for root, dirs, files in os.walk(extract_dir):
        if "ffmpeg.exe" in files and os.path.basename(root) == "bin":
            source_ffmpeg_path = os.path.join(root, "ffmpeg.exe")
            logging.info(f"ffmpeg.exe found at: {source_ffmpeg_path}")
            ffmpeg_found = True
            break
        # 혹시 모르니 다른 경로도 체크 (예: bin 폴더가 루트에 바로 있을 경우)
        # elif "ffmpeg.exe" in files and root == extract_dir:
        #     ... handle this case if needed ...

    if not ffmpeg_found:
        logging.error(
            f"ffmpeg.exe not found within the extracted files in {extract_dir}"
        )
        return False

    # 목표 디렉토리 생성
    os.makedirs(os.path.dirname(target_path), exist_ok=True)

    # ffmpeg.exe 이동
    try:
        logging.info(f"Moving {source_ffmpeg_path} to {target_path}")
        shutil.move(source_ffmpeg_path, target_path)
        logging.info("ffmpeg.exe moved successfully.")
        return True
    except Exception as e:
        logging.error(f"Failed to move ffmpeg.exe: {e}")
        return False


def main():
    logging.info("Checking if FFmpeg needs installation...")

    # 목표 경로에 ffmpeg.exe가 이미 있는지 확인
    if os.path.exists(TARGET_FFMPEG_PATH):
        logging.info(f"FFmpeg already exists at: {TARGET_FFMPEG_PATH}")
        sys.exit(0)  # 성공 종료

    logging.info("FFmpeg not found. Starting download and installation process.")

    # 임시 디렉토리 사용 (스크립트 종료 시 자동 삭제됨)
    with tempfile.TemporaryDirectory() as temp_dir:
        logging.info(f"Using temporary directory: {temp_dir}")
        # archive_dest_path = os.path.join(temp_dir, "ffmpeg.7z")
        archive_dest_path = os.path.join(temp_dir, "ffmpeg.zip")  # 파일명 .zip으로 변경
        extract_dest_dir = os.path.join(temp_dir, "extracted")

        # 1. 파일 다운로드
        if not download_file(FFMPEG_URL, archive_dest_path):
            sys.exit(1)  # 실패 종료

        # 2. 압축 해제
        if not extract_ffmpeg(archive_dest_path, extract_dest_dir):
            # 압축 해제 실패 시 부분적으로 추출된 파일이 남을 수 있음
            # TemporaryDirectory가 정리해주므로 별도 처리 불필요
            sys.exit(1)  # 실패 종료

        # 3. ffmpeg.exe 찾아서 이동
        if not find_and_move_ffmpeg(extract_dest_dir, TARGET_FFMPEG_PATH):
            sys.exit(1)  # 실패 종료

    logging.info("FFmpeg installation process completed successfully.")
    sys.exit(0)  # 성공 종료


if __name__ == "__main__":
    # 필수 라이브러리 설치 확인 관련 try-except 블록 제거
    main()
