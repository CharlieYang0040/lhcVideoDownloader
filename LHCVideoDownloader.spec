# -*- mode: python ; coding: utf-8 -*-
import glob
import os

block_cipher = None

ffmpeg_dlls = [(dll, 'libs/ffmpeg') for dll in sorted(glob.glob('libs/ffmpeg/*.dll'))]

a = Analysis(
    ['src/main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('libs/yt-dlp/yt-dlp.exe', 'libs/yt-dlp'),
        ('libs/deno/deno.exe', 'libs/deno'),
        ('libs/ffmpeg/ffmpeg.exe', 'libs/ffmpeg'),
        ('libs/ffmpeg/ffprobe.exe', 'libs/ffmpeg'),
        *ffmpeg_dlls,
        ('resources/icon.ico', 'resources'),
    ],
    hiddenimports=[
        'logging.handlers',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PySide6.QtNetwork',
        'PySide6.QtSvg',
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebChannel',
        'PySide6.QtPdf',
        'PySide6.QtPdfWidgets',
        'PySide6.Qt3DCore',
        'PySide6.Qt3DRender',
        'PySide6.QtMultimedia',
        'PySide6.QtMultimediaWidgets',
        'PySide6.QtQuick',
        'PySide6.QtQuickWidgets',
        'PySide6.QtQml',
        'PySide6.QtSql',
        'PySide6.QtCharts',
        'PySide6.QtBluetooth',
        'PySide6.QtNfc',
        'PySide6.QtPositioning',
        'PySide6.QtSensors',
        'PySide6.QtSerialPort',
        'PySide6.QtTest',
        'PySide6.QtDesigner',
        'PySide6.QtHelp',
        'tkinter',
        'unittest',
        'pydoc',
        'doctest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

_FFMPEG_DLL_NAMES = {os.path.basename(src).lower() for src, _ in ffmpeg_dlls}

_EXCLUDED_BINARY_NAMES = {
    'opengl32sw.dll',
    'qt6network.dll',
    'qtnetwork.pyd',
    'qt6svg.dll',
    'qtsvg.pyd',
    'qsvgicon.dll',
    'qsvg.dll',
    'qdirect2d.dll',
    'qminimal.dll',
}


def _keep_binary(entry):
    dest = entry[0].replace('\\', '/').lower()
    basename = os.path.basename(dest)
    if basename in _EXCLUDED_BINARY_NAMES:
        return False
    # FFmpeg shared DLLs already live beside ffmpeg.exe in libs/ffmpeg/; drop root duplicates pulled in by PE scan
    if dest == basename and basename in _FFMPEG_DLL_NAMES:
        return False
    if 'plugins/tls/' in dest or 'plugins/networkinformation/' in dest or 'plugins/iconengines/' in dest:
        return False
    if 'plugins/imageformats/' in dest and basename != 'qico.dll':
        return False
    return True


def _keep_data(entry):
    dest = entry[0].replace('\\', '/').lower()
    basename = os.path.basename(dest)
    if 'pyside6/translations/' in dest:
        return basename.endswith('_ko.qm') or basename.endswith('_en.qm')
    return True


a.binaries = [b for b in a.binaries if _keep_binary(b)]
a.datas = [d for d in a.datas if _keep_data(d)]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='LHCVideoDownloader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='resources/icon.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='LHCVideoDownloader',
)
