# LHC Video Downloader

**LHC Video Downloader**는 YouTube, Vimeo, Twitch 등 1000개 이상의 사이트를 지원하는 강력하고 직관적인 데스크탑용 비디오 다운로더입니다. 최신 `yt-dlp` 엔진을 기반으로 하며, 사용자 친화적인 GUI와 강력한 성능 최적화 기능을 제공합니다.

![스크린샷](resources/icon.png)

## ✨ 주요 기능 (Key Features)

*   **광전송급 다운로드 속도**: `yt-dlp`의 강력한 성능과 멀티 스레드/분할 다운로드 지원.
*   **스마트 포맷 선택**:
    *   **MP4**: 4K/8K 초고화질 우선 (VP9/AV1) 또는 1080p 호환성 모드(H.264) 자동 전환.
    *   **WebM**: 구글 표준 고화질 자동 선택.
    *   **변환 없음**: 인코딩 없이 원본을 그대로 가져와 즉시 저장 (초고속).
*   **강력한 포스트 프로세싱**:
    *   **GPU 가속**: NVENC (NVIDIA GPU) 하드웨어 인코딩 지원.
    *   **다양한 프리셋**: 무손실, 고화질, 최대 압축 등 용도별 설정.
*   **고급 기능**:
    *   **앱 내 로그인**: YouTube 연령 제한 동영상 다운로드 지원 (QtWebEngine 기반).
    *   **중복 처리**: 이미 받은 파일 건너뛰기 또는 덮어쓰기 옵션.
    *   **안전한 취소**: 다운로드 중 취소 시 임시 파일 자동 클린업.

---

## 📥 설치 및 실행 (Installation)

GitHub Releases 페이지에서 최신 버전을 다운로드할 수 있습니다.

1.  **[Releases 페이지](https://github.com/CharlieYang0040/lhcVideoDownloader/releases)**로 이동합니다.
2.  최신 버전의 `LHCVideoDownloader_vX.X.zip` 파일을 다운로드합니다.
3.  다운로드한 압축 파일의 압축을 풉니다.
4.  폴더 내의 **`LHCVideoDownloader.exe`** 를 더블 클릭하여 실행합니다.
    *   별도의 설치 과정이 필요 없습니다 (Portable).

---

## 📖 사용법 (Usage Guide)

앱은 크게 세 부분으로 구성되어 있습니다.

### 1. 다운로드 추가 (Add New Download)
*   **URL 입력**: 상단 입력창에 유튜브 등의 링크를 붙여넣으세요.
*   **붙여넣기**: 클립보드에 있는 주소를 자동으로 가져옵니다.
*   **다운로드 시작**: 설정을 확인한 후 버튼을 누르면 목록에 추가되고 바로 시작됩니다.

### 2. 설정 옵션 (Options)

#### 저장 및 형식
*   **저장 경로**: 파일이 저장될 위치를 지정합니다.
*   **형식 (Format)**:
    *   `최고 화질 (MP4)`: 가장 호환성이 좋은 설정 (4K 지원).
    *   `오디오만 (MP3/WAV)`: 영상을 소리 파일로 변환합니다.
*   **인증 (Auth)**:
    *   `인증 안 함` (기본값): 일반적인 영상.
    *   `앱 내 로그인`: 성인 인증이 필요한 영상을 받을 때 사용합니다. 구글 로그인 창이 뜹니다.

#### 고급 인코딩 (Advanced)
*   **코덱**: `변환 없음`(추천), `H264 (CPU)`, `NVENC (GPU)` 등 선택.
*   **품질**: `기본`, `무손실`, `최대 압축` 등 파일 크기와 화질을 조절.
*   **덮어쓰기**: 체크하면 같은 이름의 파일이 있어도 새로 받습니다.
*   **인코딩 스레드**: `0` (자동)으로 두면 CPU 성능을 최대로 사용하여 속도가 빨라집니다.
*   **다운로드 분할**: 파일을 여러 조각으로 나누어 동시에 받아 속도를 높입니다.

### 3. 작업 목록 (Task List)
*   진행 중인 다운로드의 상태(속도, 남은 시간, 퍼센트)를 실시간으로 보여줍니다.
*   **Logs**: 각 작업의 `로그` 버튼을 누르면 `yt-dlp`의 상세한 진행 상황을 볼 수 있습니다.
*   **Cancel**: 작업을 취소하고 찌꺼기 파일을 정리합니다.

---

## 🛠️ 개발자용 설정 (Development Setup)

소스 코드를 직접 실행하거나 빌드하려면 `libs` 폴더에 다음 바이너리 파일들이 필요합니다.

### 필수 바이너리 다운로드 (Libs)
앱 실행을 위해 루트 디렉토리의 `libs` 폴더 아래에 다음 구조로 파일들을 배치해야 합니다.

1.  **FFmpeg** (영상 변환 및 병합, 필수)
    *   다운로드: [gyan.dev (Windows Builds)](https://www.gyan.dev/ffmpeg/builds/)
    *   `ffmpeg-git-full.7z` 다운로드 -> 압축 해제 -> `bin` 폴더 안의 `ffmpeg.exe`, `ffprobe.exe`
    *   위치: `libs/ffmpeg/ffmpeg.exe`, `libs/ffmpeg/ffprobe.exe`

2.  **yt-dlp** (다운로드 코어 엔진, 필수)
    *   다운로드: [yt-dlp GitHub Releases](https://github.com/yt-dlp/yt-dlp/releases)
    *   `yt-dlp.exe` 다운로드
    *   위치: `libs/yt-dlp/yt-dlp.exe`

3.  **Deno** (일부 사이트 자바스크립트 처리용, 권장)
    *   다운로드: [Deno GitHub Releases](https://github.com/denoland/deno/releases)
    *   `deno-x86_64-pc-windows-msvc.zip` 다운로드 -> `deno.exe`
    *   위치: `libs/deno/deno.exe`

### 폴더 구조 예시
```text
lhcVideoDownloader/
├── libs/
│   ├── ffmpeg/
│   │   ├── ffmpeg.exe
│   │   └── ffprobe.exe
│   ├── yt-dlp/
│   │   └── yt-dlp.exe
│   └── deno/
│       └── deno.exe
├── src/
└── main.py
```

## ⚖️ 라이선스 및 주의사항
이 프로그램은 오픈 소스 프로젝트입니다. 다운로드한 콘텐츠의 저작권과 관련된 책임은 전적으로 사용자에게 있습니다. 개인적인 용도로만 사용하시기 바랍니다.
