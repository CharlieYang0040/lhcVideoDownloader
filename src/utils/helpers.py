import os
import sys
import shutil
import appdirs

APP_NAME = "LHCVideoDownloader"
APP_AUTHOR = "LHCinema"

def get_base_path():
    """ Get absolute path to resource, works for dev and for PyInstaller """
    return get_bundle_path()

def get_bundle_path():
    """Get the directory where bundled resources live."""
    if getattr(sys, 'frozen', False):
        return getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def get_app_path():
    """Get the app executable directory, or project root while running from source."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return get_bundle_path()

def get_user_data_path(*parts):
    """Get a user-writable app data path."""
    base_dir = os.environ.get("LHCVD_USER_DATA_DIR") or appdirs.user_data_dir(APP_NAME, APP_AUTHOR)
    return os.path.join(base_dir, *parts)

def get_default_download_path():
    downloads_dir = os.path.join(os.path.expanduser("~"), "Downloads")
    if os.path.isdir(downloads_dir):
        return os.path.join(downloads_dir, APP_NAME)
    return get_user_data_path("downloads")

def get_cookie_file_path():
    return get_user_data_path("cookies", "auth_cookies.txt")

def find_cookie_file_path():
    cookie_path = get_cookie_file_path()
    if os.path.exists(cookie_path):
        return cookie_path

    legacy_paths = []
    for base_dir in (get_app_path(), get_bundle_path(), os.getcwd()):
        legacy_paths.append(os.path.join(base_dir, "libs", "cookies", "auth_cookies.txt"))

    for legacy_path in legacy_paths:
        if os.path.exists(legacy_path):
            return legacy_path

    return cookie_path

def get_lib_path(name):
    """
    Get path to a library binary (yt-dlp, ffmpeg, or deno).
    Checks 'libs/{name}/{name}.exe' first.
    """
    filename = f"{name}.exe" if os.name == 'nt' else name
    search_roots = (
        get_bundle_path(),
        get_app_path(),
        os.getcwd(),
    )

    for base_dir in search_roots:
        path = os.path.join(base_dir, 'libs', name, filename)
        if os.path.exists(path):
            return path
        
    # Fallback to PATH
    return shutil.which(name)

def check_js_runtime():
    """
    Check if a supported JS runtime (deno or node) is available.
    Returns: Path to runtime or 'node'/'deno' string if in PATH, or None.
    """
    # Check bundled Deno first
    local_deno = get_lib_path('deno')
    if local_deno and os.path.exists(local_deno):
        return local_deno

    if shutil.which("deno"):
        return "deno"
    if shutil.which("node"):
        return "node"
    return None
