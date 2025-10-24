import importlib
from pathlib import Path

commands_dir = Path(__file__).parent

# Dynamically import all command modules to register themselves
for py_file in commands_dir.glob("*.py"):
    if py_file.name == "__init__.py":
        continue

    module_name = f"{__name__}.{py_file.stem}"

    importlib.import_module(module_name)
