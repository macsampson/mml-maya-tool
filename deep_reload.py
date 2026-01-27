
# Generic Deep Reload for MML Tool
import sys
import importlib
import maya.cmds as cmds

def deep_reload(package_name="MML"):
    """
    Recursively reloads all active modules in the specified package.
    """
    # 1. Identify all loaded modules belonging to the package
    modules_to_reload = []
    for name, module in sys.modules.items():
        if name.startswith(package_name) and module is not None:
             modules_to_reload.append((name, module))
    
    # 2. Sort by name to ensure consistent order (parents usually before children)
    modules_to_reload.sort(key=lambda x: x[0])

    print(f"\n--- Deep Reloading '{package_name}' ({len(modules_to_reload)} modules) ---")
    
    for name, module in modules_to_reload:
        try:
            importlib.reload(module)
        except Exception as e:
            print(f"FAILED to reload {name}: {e}")
            
    print(f"--- Reload Complete ---\n")

# 1. Ensure the package is imported at least once
try:
    import MML.core.maya_importer
    import MML.ui.main_window
except ImportError:
    pass

# 2. Perform Deep Reload
deep_reload("MML")

# 3. Relaunch UI
print("Relaunching MML Importer UI...")
from MML.ui import main_window
main_window.show_mml_importer()
