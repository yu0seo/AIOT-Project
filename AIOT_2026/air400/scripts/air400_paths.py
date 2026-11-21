"""Shared locations for the AIR-400 study, separate from its runtime environment."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "air400"
DATA = PROJECT / "00_공통자료"
BEFORE = PROJECT / "01_파인튜닝전"
FINETUNE = PROJECT / "02_Chest_파인튜닝"
AFTER = PROJECT / "03_파인튜닝후"
PRESENTATION = PROJECT / "04_PT자료"
ARCHIVE = PROJECT / "05_기존모델비교실험"
# Windows virtual environments contain absolute launcher paths. Keep this
# existing environment and native compiler caches in their original location.
RUNTIME = ROOT / "data" / "air400_benchmark" / "runtime"
PYTHON = ROOT / "data" / "air400_benchmark" / "env" / "Scripts" / "python.exe"
