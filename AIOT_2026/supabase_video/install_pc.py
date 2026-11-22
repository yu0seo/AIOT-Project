"""Install only the PC video download/validation tools in an isolated environment."""
import os
from pathlib import Path
import subprocess
import sys
import venv

root = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".config")) / "AIOT-SupabaseVideo"
environment = root / "env"
python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
if not python.exists():
    venv.EnvBuilder(with_pip=True).create(environment)
subprocess.run([str(python), "-m", "pip", "install", "-r", str(Path(__file__).with_name("requirements-pc.txt"))], check=True)
print(f"PC download environment ready: {python}")
