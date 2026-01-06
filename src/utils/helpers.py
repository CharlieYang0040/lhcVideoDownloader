import os
import sys
import shutil

def get_base_path():
    """ Get absolute path to resource, works for dev and for PyInstaller """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def get_lib_path(name):
    """
    Get path to a library binary (yt-dlp, ffmpeg, or deno).
    Checks 'libs/{name}/{name}.exe' first.
    """
    base_dir = os.getcwd()
    # Handle PyInstaller frozen state
    if getattr(sys, 'frozen', False):
        base_dir = sys._MEIPASS
        
    # Expected layout: libs/yt-dlp/yt-dlp.exe
    # name is 'yt-dlp', 'ffmpeg', 'deno'
    filename = f"{name}.exe" if os.name == 'nt' else name
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
