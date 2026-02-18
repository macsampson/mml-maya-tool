import sys
import importlib

DEV_MODE = True


def __bootstrap():
    print("Dev mode active, reloading MML package...")
    package_name = __name__
    # Use a list comprehension to snapshot the keys
    to_reload = [n for n in sys.modules if n.startswith(package_name + ".")]
    to_reload.sort()

    for module_name in to_reload:
        try:
            importlib.reload(sys.modules[module_name])
        except Exception as e:
            print(f"MML Reload Error: {module_name} -> {e}")

if DEV_MODE:
    __bootstrap()

# --- API EXPOSURE ---
# We do this after bootstrapping so these references are always fresh.
from .parsers.bin_reader import MMLAsset, MMLBinReader
from .core.maya_importer import MMLMayaImporter
from .ui.preview_widget import AssetPreviewWidget
from .ui.main_window import MMLImporterUI, show_mml_importer
from .parsers.ebd_reader import EBDReader
from .converters.fbx_exporter import FBXExporter
from .parsers.tim2png import read_mml_tim

def launch():
    show_mml_importer()

__all__ = [
    'MMLAsset', 'MMLBinReader', 'MMLMayaImporter',
    'AssetPreviewWidget', 'MMLImporterUI', 'show_mml_importer',
    'EBDReader', 'FBXExporter', 'read_mml_tim', 'launch'
]