from pathlib import Path
from babycam.worker import main

if __name__ == "__main__":
    raise SystemExit(main(Path(__file__).resolve().with_name(".env")))
