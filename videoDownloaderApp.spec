# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[('libs/ffmpeg/bin/ffmpeg.exe', 'libs/ffmpeg/bin')],
    datas=[('resources/icon.png', '.'), ('resources/icon.ico', '.')],
    hiddenimports=[
        'cryptography.hazmat.backends.openssl', # Cryptography 백엔드 명시적 포함
        'PySide6.QtWebEngineCore',             # QtWebEngine 관련 모듈 명시
        'PySide6.QtNetwork'                    # WebEngine이 의존할 수 있음
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 사용하지 않을 것으로 예상되는 표준 라이브러리 제외
        'tkinter',
        'sqlite3',
        'unittest',
        'test',
        'distutils',
        'setuptools',
        '_decimal', # 경우에 따라 필요할 수 있음
        'bz2',
        'lzma',
        'curses',
        'lib2to3',
        'xmlrpc',
        'pydoc_data',
        # PySide6의 사용하지 않을 것으로 예상되는 모듈 제외
        'PySide6.QtSql',
        'PySide6.QtTest',
        'PySide6.QtXml',
        'PySide6.QtQml',          # QML 사용 안하면 제외
        'PySide6.QtQuick',        # QML 사용 안하면 제외
        # 기타 불필요 라이브러리 (필요시 추가)
        # 'numpy', 'pandas' 등 프로젝트와 무관한 큰 라이브러리가 실수로 포함될 경우
    ],
    noarchive=False,
    optimize=0, # 최적화 레벨 (0, 1, 2) - 높이면 빌드 시간 증가, 약간의 크기 감소 가능
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='videoDownloaderApp',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False, # 실행 파일 및 DLL에서 심볼 제거 (True로 변경)
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True, # 콘솔 창 표시 (False로 하면 GUI만 표시)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='resources/icon.ico',
)
