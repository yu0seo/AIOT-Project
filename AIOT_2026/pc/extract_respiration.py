"""영상 → DeepPhys → 30초/10Hz 파형 + 추정 BPM. 수동 승인 없이 실행한다."""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys

import numpy as np

DEFAULT_REPO = Path(r'C:\Users\OHS\air-400')
VIDEO_SUFFIXES = {'.mp4', '.avi', '.mov', '.mkv'}


def sha256(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def discover_videos(source):
    source = Path(source).resolve()
    if not source.exists():
        raise ValueError(f'입력 경로가 없습니다: {source}')
    candidates = [source] if source.is_file() else source.rglob('*')
    return sorted(p for p in candidates if p.is_file() and p.suffix.lower() in VIDEO_SUFFIXES
                  and not any(part.startswith('.') or part == '__MACOSX' for part in p.relative_to(source.parent if source.is_file() else source).parts))


def video_identity(path):
    path = Path(path).resolve()
    parts = path.parts
    for i, part in enumerate(parts[:-2]):
        if part in ('AIR_125', 'AIR_400') and re.fullmatch(r'S\d{2}', parts[i+1]):
            # Include a path hash for nested recordings / different extensions.
            suffix = '' if i+3 == len(parts) and path.suffix.lower() == '.mp4' else '_' + hashlib.sha256(str(path).encode()).hexdigest()[:12]
            stem = re.sub(r'[^A-Za-z0-9_-]', '_', path.stem)
            return f'{part}_{parts[i+1]}_{stem}{suffix}', f'{part}:{parts[i+1]}'
    stem = re.sub(r'[^A-Za-z0-9_-]', '_', path.stem)[:60] or 'video'
    return f'{stem}_{hashlib.sha256(str(path).encode()).hexdigest()[:12]}', ''


def window_starts(frames, fps, stride):
    if not math.isfinite(fps) or fps < 10 or abs(fps - round(fps)) > .001:
        raise ValueError(f'정수 FPS >=10인 영상이 필요합니다. 실제 FPS={fps}; 임의 반올림하지 않습니다.')
    if not isinstance(stride, int) or isinstance(stride, bool) or stride <= 0:
        raise ValueError('stride는 양의 정수(초)여야 합니다.')
    fs = int(round(fps))
    # Count in frames: 29.99 seconds must never become a complete window.
    if frames < 30 * fs:
        return []
    return list(range(0, (int(frames) - 30 * fs) // fs + 1, stride))


def probe_video(path):
    import cv2
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise ValueError('영상 파일을 열 수 없습니다.')
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if frames <= 0:
            raise ValueError('영상 프레임 수가 유효하지 않습니다.')
        return {'fps': fps, 'frames': frames}
    finally:
        cap.release()


def make_plan(source, stride):
    videos = discover_videos(source)
    if not videos:
        raise ValueError('추출할 영상이 없습니다.')
    plan, excluded = [], []
    for video in videos:
        try:
            info = probe_video(video)
            starts = window_starts(info['frames'], info['fps'], stride)
            if not starts:
                raise ValueError('30초보다 짧은 영상입니다.')
            video_id, subject_id = video_identity(video)
            plan.append({'video': video, 'video_id': video_id, 'subject_id': subject_id,
                         'fps': info['fps'], 'starts': starts})
        except (ValueError, OSError) as error:
            excluded.append({'video': str(video), 'start_sec': '', 'reason': str(error)})
    return plan, excluded


def save_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def validate_prediction(pred):
    fs = float(pred['fs'])
    if not math.isfinite(fs) or fs < 10 or fs != int(fs):
        raise ValueError('추론 결과의 샘플링 주파수가 유효하지 않습니다.')
    expected = int(30 * fs)
    for key in ('raw_model', 'respiration', 'time_sec'):
        signal = np.asarray(pred[key])
        if signal.shape != (expected,) or not np.isfinite(signal).all():
            raise ValueError(f'{key}: 완전한 30초 추론 결과가 아닙니다. 늘리거나 패딩하지 않습니다.')
    if not np.allclose(pred['time_sec'], np.arange(expected)/fs, rtol=0, atol=1e-4):
        raise ValueError('추론 결과의 시간축이 샘플링 주파수와 다릅니다.')
    waveform = np.asarray(pred['x_10hz'], dtype=np.float32)
    bpm = float(pred['pred_rr_bpm'])
    if waveform.shape != (300,) or not np.isfinite(waveform).all() or not math.isfinite(bpm) or bpm <= 0:
        raise ValueError('파형은 유한한 값 300개, BPM은 유한한 양수여야 합니다.')
    return waveform, bpm


def write_csv(path, rows, fields):
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def draw_waveform(path, waveform, row):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(10, 3))
    ax.plot(np.arange(300)/10 + row['start_sec'], waveform, linewidth=1)
    ax.set(xlabel='Video time (s)', ylabel='DeepPhys prediction (a.u.)',
           title=f"{row['video_id']} | {row['start_sec']}-{row['end_sec']}s | {row['bpm_estimate']:.2f} BPM")
    ax.grid(alpha=.2)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def extract(source, output, extractor, stride=30, plots=True, limit_windows=0):
    """Reusable batch entry point; one extractor is loaded once for all videos."""
    plan, errors = make_plan(source, stride)
    source, output = Path(source).resolve(), Path(output).resolve()
    if limit_windows < 0:
        raise ValueError('limit-windows는 0 이상이어야 합니다.')
    ids = [job['video_id'] for job in plan]
    if len(ids) != len(set(ids)):
        raise ValueError('영상 ID가 중복됩니다. 서로 다른 데이터 복사본은 별도 --input/--output으로 실행하세요.')
    identity = {'format_version': 1, 'input': str(source), 'window_sec': 30, 'stride_sec': stride,
                'output_fs': 10, 'script_sha256': sha256(__file__), 'extractor': extractor.receipt}
    signature = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    run_file = output/'run.json'
    if run_file.exists():
        if json.loads(run_file.read_text(encoding='utf-8'))['signature'] != signature:
            raise ValueError('입력 경로/모델/추론 설정이 이전 실행과 다릅니다. 새 --output 폴더를 지정하세요.')
    elif output.exists() and any(output.iterdir()):
        raise ValueError('출력 폴더가 비어 있지 않고 run.json이 없습니다. 새 --output 폴더를 지정하세요.')
    output.mkdir(parents=True, exist_ok=True)
    if not run_file.exists():
        save_json(run_file, {'signature': signature, **identity})
    rows, waveforms, bpms = [], [], []
    reused = attempted = 0
    total = sum(len(job['starts']) for job in plan)
    total = min(total, limit_windows) if limit_windows else total
    for job in plan:
        if attempted == total:
            break
        source_hash = sha256(job['video'])
        folder = output/'windows'/job['video_id']
        folder.mkdir(parents=True, exist_ok=True)
        for start in job['starts']:
            if attempted == total:
                break
            attempted += 1
            path = folder/f'{start:06d}.npz'
            if path.exists():
                # Do not silently overwrite cached data from another source/run.
                with np.load(path, allow_pickle=False) as cached:
                    row = json.loads(str(cached['metadata_json'].item()))
                    if (row['source_sha256'] != source_hash or row['run_signature'] != signature
                            or row['video_id'] != job['video_id'] or row['start_sec'] != start or row['end_sec'] != start+30):
                        raise ValueError(f'완료 파일과 원본/설정이 다릅니다: {path}; 새 출력 폴더를 사용하세요.')
                    pred = {key: cached[key] for key in ('raw_model', 'respiration', 'time_sec', 'x_10hz', 'fs', 'pred_rr_bpm')}
                    waveform, bpm = validate_prediction(pred)
                    if float(pred['fs']) != round(job['fps']):
                        raise ValueError('완료 파일의 FPS와 원본 영상이 다릅니다.')
                reused += 1
            else:
                try:
                    pred = extractor.predict_video(job['video'], start)
                    waveform, bpm = validate_prediction(pred)
                    if float(pred['fs']) != round(job['fps']):
                        raise ValueError('영상 FPS와 추론 결과 시간축이 다릅니다.')
                    row = {'video_id': job['video_id'], 'subject_id': job['subject_id'], 'video': str(job['video']),
                           'start_sec': start, 'end_sec': start+30, 'source_fps': job['fps'], 'samples': 300,
                           'bpm_estimate': bpm, 'waveform_std': float(waveform.astype(np.float64).std()), 'label_status': 'unreviewed',
                           'window_file': path.relative_to(output).as_posix(), 'source_sha256': source_hash,
                           'run_signature': signature}
                    temporary = path.with_suffix('.tmp')
                    with temporary.open('wb') as stream:
                        np.savez_compressed(stream, **{key: pred[key] for key in ('raw_model', 'respiration', 'time_sec', 'fs')},
                                            x_10hz=waveform, pred_rr_bpm=bpm, metadata_json=json.dumps(row, ensure_ascii=False))
                    temporary.replace(path)
                except Exception as error:
                    errors.append({'video': str(job['video']), 'start_sec': start, 'reason': str(error)})
                    print(f'[{attempted}/{total}] 실패: {job["video_id"]} {start}s: {error}', flush=True)
                    continue
            if plots and not path.with_suffix('.png').exists():
                draw_waveform(path.with_suffix('.png'), waveform, row)
            rows.append({'sample_index': len(rows), **row})
            waveforms.append(waveform[None, :])
            bpms.append(bpm)
            print(f'[{attempted}/{total}] {job["video_id"]} {start}-{start+30}s | {bpm:.2f} BPM', flush=True)
    arrays = {'X': np.stack(waveforms).astype(np.float32) if waveforms else np.empty((0,1,300), dtype=np.float32),
              'bpm': np.asarray(bpms, dtype=np.float32)}
    for name, array in arrays.items():
        temporary = output/f'{name}.tmp'
        with temporary.open('wb') as stream:
            np.save(stream, array, allow_pickle=False)
        temporary.replace(output/f'{name}.npy')
    fields = ['sample_index', 'video_id', 'subject_id', 'video', 'start_sec', 'end_sec', 'source_fps', 'samples',
              'bpm_estimate', 'waveform_std', 'label_status', 'window_file', 'source_sha256', 'run_signature']
    write_csv(output/'metadata.csv', rows, fields)
    write_csv(output/'errors.csv', errors, ['video', 'start_sec', 'reason'])
    report = {'status': 'complete_with_errors' if errors else 'complete', 'windows': len(rows), 'reused': reused,
              'attempted': attempted, 'planned': sum(len(job['starts']) for job in plan), 'limited': bool(limit_windows),
              'shape': list(arrays['X'].shape), 'window_sec': 30, 'stride_sec': stride, 'sample_hz': 10,
              'errors': errors, 'label_status': 'unreviewed', 'bpm_source': 'DeepPhys + existing AIR postprocessor'}
    save_json(output/'summary.json', report)
    print(f'완료: {output} | X={arrays["X"].shape}, BPM={arrays["bpm"].shape}, 기존 결과 재사용={reused}', flush=True)
    return report


def load_extractor(repo, config, checkpoint):
    adapter_dir = Path(repo).resolve()/'normal_pipeline'
    adapter_path = adapter_dir/'inference_adapter.py'
    if not adapter_path.is_file():
        raise ValueError(f'기존 AIR 추론 adapter가 없습니다: {adapter_path}')
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(adapter_dir))
    spec = importlib.util.spec_from_file_location('air400_batch_adapter', adapter_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.AirExtractor(repo, config, checkpoint)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--air-repo', type=Path, default=DEFAULT_REPO)
    parser.add_argument('--input', type=Path, help='동영상 하나 또는 동영상 폴더. 기본: AIR 저장소/data')
    parser.add_argument('--output', type=Path, help='기본: AIR 저장소/output/training_30s')
    parser.add_argument('--config', type=Path, help='기본: configs/inference/deepphys_deep_infer.yaml')
    parser.add_argument('--checkpoint', type=Path, help='기본: checkpoints/DeepPhys_Deep_Body_best.pth')
    parser.add_argument('--stride', type=int, default=30, help='30초 파형의 시작 간격(초). 기본 30, 겹침 추출은 5')
    parser.add_argument('--limit-windows', type=int, default=0, help='처음 N개 구간만 시험. 0이면 전체')
    parser.add_argument('--no-plots', action='store_true', help='구간별 PNG 그래프 생략')
    parser.add_argument('--dry-run', action='store_true', help='모델 실행 없이 대상 영상/구간 수만 확인')
    args = parser.parse_args(argv)
    repo = args.air_repo.resolve()
    source = args.input or repo/'data'
    output = args.output or repo/'output/training_30s'
    config = args.config or repo/'configs/inference/deepphys_deep_infer.yaml'
    checkpoint = args.checkpoint or repo/'checkpoints/DeepPhys_Deep_Body_best.pth'
    if args.stride <= 0 or args.limit_windows < 0:
        parser.error('--stride는 양수, --limit-windows는 0 이상이어야 합니다.')
    try:
        plan, excluded = make_plan(source, args.stride)
        print(f'대상 영상 {len(plan)}개, 30초 구간 {sum(len(v["starts"]) for v in plan)}개, 제외 영상 {len(excluded)}개', flush=True)
        if args.dry_run:
            for error in excluded:
                print(f'제외: {error["video"]}: {error["reason"]}')
            return 0
        extractor = load_extractor(repo, config, checkpoint)
        report = extract(source, output, extractor, args.stride, not args.no_plots, args.limit_windows)
        return 0 if report['windows'] and not report['errors'] else 2
    except KeyboardInterrupt:
        print('중단했습니다. 같은 명령으로 다시 실행하면 완료된 구간을 재사용합니다.', file=sys.stderr)
        return 130
    except (ValueError, OSError, RuntimeError, KeyError) as error:
        print(f'오류: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
