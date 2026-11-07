"""Windows에서도 실행할 수 있는 최소 명령행 인터페이스."""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

from .features import FeatureConfig


def load_config(path):
    config = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    FeatureConfig(**config["feature"])
    if config["window_seconds"] != [3, 5, 10]:
        raise ValueError("초기 비교 실험은 window_seconds=[3,5,10]을 사용합니다.")
    for key in ("epochs", "patience", "batch_size", "hidden_size", "num_layers", "cpu_threads"):
        if not isinstance(config[key], int) or config[key] < 1:
            raise ValueError(f"{key}는 양의 정수여야 합니다.")
    if not isinstance(config["bootstrap_repeats"], int) or config["bootstrap_repeats"] < 0:
        raise ValueError("bootstrap_repeats는 음수가 아닌 정수여야 합니다.")
    if not 0 <= config["dropout"] < 1 or not 0 <= config["max_validation_fpr"] < 1:
        raise ValueError("dropout/FPR은 0 이상 1 미만이어야 합니다.")
    for key in ("learning_rate", "weight_decay", "stride_seconds"):
        if not np.isfinite(config[key]) or config[key] <= 0:
            raise ValueError(f"{key}는 양의 유한한 수여야 합니다.")
    stride = config["stride_seconds"]*config["feature"]["sample_hz"]
    if not float(stride).is_integer():
        raise ValueError("stride_seconds는 정수 개의 샘플에 대응해야 합니다.")
    return config


def main():
    parser = argparse.ArgumentParser(description="IDD 좌표 기반 음주 조건 LSTM 연구 도구")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("inspect", "train"):
        sub = commands.add_parser(command, help="데이터 실사" if command == "inspect" else "3/5/10초 학습·평가")
        sub.add_argument("--data-root", required=True, type=Path, help="no-video 또는 Processed 폴더")
        sub.add_argument("--config", required=True, type=Path, help="학습 설정 JSON")
        sub.add_argument("--output", required=True, type=Path, help="새 결과 폴더, 기존 폴더 덮어쓰기 금지")
        if command == "train":
            sub.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    replay = commands.add_parser("replay-idd", help="실제 ego CSV로 온라인 추론 재생 검증")
    replay.add_argument("--bundle", required=True, type=Path)
    replay.add_argument("--ego-csv", required=True, type=Path)
    replay.add_argument("--output", required=True, type=Path)
    search = commands.add_parser("search", help="기존 학습 참가자 내부에서 개선 후보 교차검증")
    search.add_argument("--data-root", required=True, type=Path)
    search.add_argument("--config", required=True, type=Path)
    search.add_argument("--search-config", required=True, type=Path)
    search.add_argument("--reference-run", required=True, type=Path)
    search.add_argument("--output", required=True, type=Path)
    finalize = commands.add_parser("finalize", help="CV 선택 후보 재학습과 고정 테스트 평가")
    finalize.add_argument("--data-root", required=True, type=Path)
    finalize.add_argument("--search-run", required=True, type=Path)
    finalize.add_argument("--reference-run", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == "replay-idd":
            from .inference import replay_idd
            replay_idd(args.bundle, args.ego_csv, args.output)
        elif args.command == "search":
            from .tuning import run_search
            search_config = json.loads(args.search_config.read_text(encoding="utf-8-sig"))
            run_search(args.data_root, load_config(args.config), search_config, args.reference_run, args.output)
        elif args.command == "finalize":
            from .improvement import finalize_search
            finalize_search(args.data_root, args.search_run, args.reference_run)
        else:
            from .experiment import inspect_dataset, run_experiment
            config = load_config(args.config)
            if args.command == "inspect":
                _, _, summary = inspect_dataset(args.data_root, config, args.output)
            else:
                summary = run_experiment(args.data_root, config, args.output, args.device)
                summary = {"selected_seconds": summary["selection_seconds"]}
            print(json.dumps(summary, ensure_ascii=False, indent=2))
    except (ValueError, FileNotFoundError, FileExistsError, KeyError) as error:
        print(f"실행 중단: {error}", file=sys.stderr)
        raise SystemExit(1) from error
