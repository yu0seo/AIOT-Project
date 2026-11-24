"""AIR normal-only dataset builder. See README_ko.md for Windows commands."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re

import h5py
import numpy as np
from scipy.signal import resample_poly


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    tmp.replace(path)


def discover(air125=None, air400=None):
    clips = []
    for name, root in [('AIR_125', air125), ('AIR_400', air400)]:
        if root is None:
            continue
        root = Path(root).resolve()
        if not root.is_dir():
            raise ValueError(f'Data root does not exist: {root}')
        for sub in sorted(root.iterdir()):
            if not sub.is_dir() or not re.fullmatch(r'S\d{2}', sub.name):
                continue
            for video in sorted(sub.iterdir()):
                if video.suffix.lower() != '.mp4':
                    continue
                label = (sub / 'out' if name == 'AIR_400' else sub) / (video.stem + '.hdf5')
                clips.append({'id': f'{name}_{sub.name}_{video.stem}', 'subject': f'{name}:{sub.name}',
                              'video': video.as_posix(), 'label': label.as_posix()})
    return clips


def read_label(path, duration, label_key='respiration', time_key=None, label_fs=None):
    keys = {}
    with h5py.File(path, 'r') as f:
        f.visititems(lambda name, obj: keys.update({name: {'shape': list(obj.shape), 'dtype': str(obj.dtype)}})
                     if isinstance(obj, h5py.Dataset) else None)
        if label_key not in f:
            raise ValueError(f'Missing label key {label_key}; actual datasets: {keys}')
        y = np.asarray(f[label_key], dtype=np.float64).squeeze()
        if y.ndim != 1 or len(y) < 2 or not np.isfinite(y).all():
            raise ValueError(f'Invalid label vector: {path}, shape={y.shape}')
        if time_key:
            if time_key not in f:
                raise ValueError(f'Missing time key {time_key}; actual datasets: {keys}')
            t = np.asarray(f[time_key], dtype=np.float64).squeeze()
            mode = 'explicit_seconds'
        elif label_fs:
            if not np.isfinite(label_fs) or label_fs <= 0:
                raise ValueError('label_fs must be positive')
            t = np.arange(len(y)) / label_fs
            mode = 'explicit_label_fs'
        else:
            # Same full-duration assumption as upstream BaseDataset._resample_ppg.
            # This is a review axis, never proof of synchronization or normality.
            t = np.linspace(0, duration, len(y), endpoint=False)
            mode = 'duration_mapped_requires_alignment_review'
    if t.shape != y.shape or not np.isfinite(t).all() or np.any(np.diff(t) <= 0):
        raise ValueError(f'Invalid/non-monotonic label timestamps: {path}')
    return t, y, mode, keys


def window_starts(duration, intervals):
    return [s for s in range(0, max(0, math.floor((duration - 30 + 1e-8) / 5) + 1) * 5, 5)
            if any(a <= s + 1e-8 and s + 30 <= b + 1e-8 for a, b in intervals)]


def to_10hz(signal, fs):
    y = np.asarray(signal, dtype=np.float64).reshape(-1)
    if not np.isfinite(fs) or fs < 10 or not np.isfinite(y).all():
        raise ValueError('Non-finite signal or invalid sampling rate (minimum 10Hz)')
    if abs(len(y) / fs - 30) > 1e-7:
        raise ValueError(f'Expected a full 30s inference; got {len(y)} samples at {fs}Hz. No stretching/padding.')
    ratio = Fraction(10 / fs).limit_denominator(10000)
    result = resample_poly(y, ratio.numerator, ratio.denominator, padtype='line')
    if result.shape != (300,) or not np.isfinite(result).all():
        raise ValueError(f'Resampling produced {result.shape}, expected (300,)')
    return result.astype(np.float32)


def subject_split(subjects, seed=100):
    subjects = sorted(set(subjects))
    if len(subjects) < 3:
        raise ValueError('At least three eligible subjects required for train/val/test')
    shuffled = np.random.default_rng(seed).permutation(subjects).tolist()
    n_val = max(1, int(round(len(subjects) * .15)))
    n_test = max(1, int(round(len(subjects) * .15)))
    n_train = len(subjects) - n_val - n_test
    return {s: ('train' if i < n_train else 'val' if i < n_train + n_val else 'test')
            for i, s in enumerate(shuffled)}


def fit_scaler(train):
    train = np.asarray(train, dtype=np.float64)
    if not train.size or not np.isfinite(train).all() or train.std() <= 1e-12:
        raise ValueError('Train set is empty, non-finite, or globally constant')
    return {'mean': float(train.mean()), 'std': float(train.std()), 'fitted_on': 'train_only', 'fs': 10, 'samples': 300}


def normalize(x, stats):
    return ((np.asarray(x, dtype=np.float64) - stats['mean']) / stats['std']).astype(np.float32)


def check_provenance(prov, splits, allow_unknown):
    if prov.get('status') != 'known':
        if not allow_unknown:
            raise ValueError('Extractor training subjects unknown; supply provenance or --allow-unknown-extractor-training for exploratory use')
        return False
    if not isinstance(prov.get('training_subjects'), list):
        raise ValueError('Known provenance requires training_subjects list')
    if any(not isinstance(s, str) or not re.fullmatch(r'AIR_(125|400):S\d{2}', s) for s in prov['training_subjects']):
        raise ValueError('Extractor AIR training subject IDs require explicit AIR_125:Sxx/AIR_400:Sxx namespaces')
    overlap = set(prov['training_subjects']) & {s for s, split in splits.items() if split != 'train'}
    if overlap:
        raise ValueError(f'Extractor was trained on held-out infants: {sorted(overlap)}')
    return True


def scan(args):
    from inference_adapter import read_video_info
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    out = args.out.resolve()
    if (out / 'manifest.json').exists():
        if not args.refresh_unreviewed or load_json(out / 'approvals.json')['approvals']:
            raise ValueError('Manifest exists. Use a new --out directory, or --refresh-unreviewed only if no approvals exist.')
    review = out / 'review'
    review.mkdir(parents=True, exist_ok=True)
    clips = discover(args.air125, args.air400)
    if not clips:
        raise ValueError('No local MP4s found under Sxx folders')
    seen = {}
    links = []
    for index, clip in enumerate(clips, 1):
        try:
            if not Path(clip['label']).is_file():
                raise ValueError('Missing paired HDF5 label')
            clip.update(read_video_info(clip['video']))
            clip['video_sha256'] = digest(clip['video'])
            clip['label_sha256'] = digest(clip['label'])
            t, y, mode, keys = read_label(clip['label'], clip['duration'], args.label_key, args.time_key, args.label_fs)
            clip.update(label_key=args.label_key, time_key=args.time_key, label_fs=args.label_fs,
                        label_time_mode=mode, hdf5_datasets=keys, label_samples=len(y),
                        reviewable_start=max(0., float(t[0])),
                        reviewable_end=min(clip['duration'], float(t[-1] + np.median(np.diff(t)))))
            with h5py.File(clip['label'], 'r') as f:
                clip['hdf5_attrs'] = {k: str(v) for k, v in f.attrs.items()}
                clip['annotation_filename'] = str(f['filename'][()]) if 'filename' in f else None
            if clip['duration'] < 30:
                raise ValueError('Video shorter than 30 seconds')
            if clip['fps'] < 10 or abs(clip['fps'] - round(clip['fps'])) > 1e-3:
                raise ValueError('Unsupported FPS; requires integer FPS >=10 without silent rounding')
            if clip['video_sha256'] in seen:
                raise ValueError(f"Duplicate video bytes: {seen[clip['video_sha256']]}")
            seen[clip['video_sha256']] = clip['id']
            clip['status'] = 'pending_review'
            fig, ax = plt.subplots(figsize=(12, 3))
            ax.plot(t, y, linewidth=.8)
            ax.set(xlabel='Video time (seconds; verify alignment)', ylabel='Reference annotation', title=clip['id'])
            ax.grid(True, alpha=.3)
            fig.tight_layout()
            fig.savefig(review / f"{clip['id']}.png", dpi=120)
            plt.close(fig)
            links.append(f'<li><a href="{clip["id"]}.html">{clip["id"]}</a> ({clip["duration"]:.2f}s)</li>')
        except (ValueError, OSError, KeyError) as e:
            clip['status'] = 'excluded'
            clip['reason'] = str(e)
        if index % 50 == 0:
            print(f'Scanned {index}/{len(clips)}', flush=True)
    annotations_without_video = []
    for name, root in [('AIR_125', args.air125), ('AIR_400', args.air400)]:
        if root is None:
            continue
        pattern = 'S*/out/*.hdf5' if name == 'AIR_400' else 'S*/*.hdf5'
        for label in sorted(root.glob(pattern)):
            video = (label.parent.parent if name == 'AIR_400' else label.parent) / (label.stem + '.mp4')
            if not video.exists():
                annotations_without_video.append(str(label.resolve()))
    manifest = {'schema': 1, 'created_utc': datetime.now(timezone.utc).isoformat(), 'clips': clips,
                'annotations_without_local_video': annotations_without_video}
    save_json(out / 'manifest.json', manifest)
    save_json(out / 'approvals.json', {'manifest_sha256': digest(out / 'manifest.json'), 'approvals': {}})
    (review / 'index.html').write_text('<!doctype html><html lang="ko"><meta charset="utf-8"><h1>정상 구간 수동 검토</h1>'
                                     '<p>아래 영상과 정답 파형을 확인한 뒤 CLI로 구간을 승인하세요. 현재 승인된 구간은 없습니다.</p><ul>'
                                     + ''.join(links) + '</ul></html>', encoding='utf-8')
    from review_media import repair
    repair(out)
    print(json.dumps(dict(Counter(c['status'] for c in clips)), ensure_ascii=False))
    print(f'Review: {review / "index.html"}')


def verified_reviews(workdir):
    workdir = Path(workdir)
    manifest = load_json(workdir / 'manifest.json')
    reviews = load_json(workdir / 'approvals.json')
    if reviews['manifest_sha256'] != digest(workdir / 'manifest.json'):
        raise ValueError('Manifest changed since review; rescan and review again')
    return manifest, reviews


def approved_intervals(clip, review):
    required = ('video_reviewed', 'label_reviewed', 'alignment_confirmed', 'quality_acceptable')
    if not all(review.get(k) is True for k in required) or not review.get('reviewer', '').strip():
        raise ValueError(f"Incomplete explicit review: {clip['id']}")
    if review.get('video_sha256') != clip['video_sha256'] or review.get('label_sha256') != clip['label_sha256']:
        raise ValueError('Approval hashes do not match this clip')
    intervals = review.get('normal_intervals', [])
    if not intervals:
        raise ValueError('No explicitly approved normal intervals')
    for interval in intervals:
        if len(interval) != 2 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in interval):
            raise ValueError('Intervals must be finite [start_seconds, end_seconds] pairs')
        a, b = interval
        if not 0 <= a < b <= clip['duration'] + 1e-8:
            raise ValueError('Approved interval outside video bounds')
        if a < clip.get('reviewable_start', 0) - 1e-8 or b > clip.get('reviewable_end', clip['duration']) + 1e-8:
            raise ValueError('Approved interval outside reference-label coverage')
    return intervals


def approve(args):
    manifest, reviews = verified_reviews(args.workdir)
    matches = [c for c in manifest['clips'] if c['id'] == args.clip]
    if len(matches) != 1 or matches[0]['status'] != 'pending_review':
        raise ValueError('Clip not eligible or unknown')
    clip = matches[0]
    if digest(clip['video']) != clip['video_sha256'] or digest(clip['label']) != clip['label_sha256']:
        raise ValueError('Source changed since scan; rescan before approving')
    review = {'normal_intervals': args.normal, 'reviewer': args.reviewer.strip(), 'notes': args.notes,
              'video_reviewed': args.video_reviewed, 'label_reviewed': args.label_reviewed,
              'alignment_confirmed': args.alignment_confirmed, 'quality_acceptable': args.quality_acceptable,
              'reviewed_utc': datetime.now(timezone.utc).isoformat(),
              'video_sha256': clip['video_sha256'], 'label_sha256': clip['label_sha256']}
    intervals = approved_intervals(clip, review)
    starts = window_starts(clip['duration'], intervals)
    if not starts:
        raise ValueError('These intervals contain no complete 30s window on the 5s grid')
    reviews['approvals'][clip['id']] = review
    save_json(args.workdir / 'approvals.json', reviews)
    print(f"Approved by {review['reviewer']}: {clip['id']} -> {len(starts)} candidate windows")


def plan_windows(workdir):
    manifest, reviews = verified_reviews(workdir)
    clips, planned = [], []
    for clip in manifest['clips']:
        review = reviews['approvals'].get(clip['id'])
        if review is None:
            continue
        if clip['status'] != 'pending_review':
            raise ValueError('Excluded clips cannot be approved')
        intervals = approved_intervals(clip, review)
        if digest(clip['video']) != clip['video_sha256'] or digest(clip['label']) != clip['label_sha256']:
            raise ValueError(f"Changed source file: {clip['id']}")
        starts = window_starts(clip['duration'], intervals)
        if starts:
            clips.append(clip)
            planned.extend((clip, start) for start in starts)
    if not planned:
        raise ValueError('No explicitly approved windows. Review real videos and labels first.')
    return clips, planned


def split_command(args):
    clips, _ = plan_windows(args.workdir)
    path = args.workdir / 'splits.json'
    if path.exists():
        raise ValueError('splits.json already exists; preserve the fixed subject split')
    save_json(path, {'seed': args.seed, 'subjects': subject_split([c['subject'] for c in clips], args.seed)})
    print(f'Fixed subject assignments: {path}')


def receipt_signature(receipt):
    return hashlib.sha256(json.dumps(receipt, sort_keys=True).encode('utf-8')).hexdigest()


def save_prediction(path, pred, attrs):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp.hdf5')
    with h5py.File(temp, 'w') as f:
        for key in ('time_sec', 'raw_model', 'respiration', 'x_10hz'):
            f.create_dataset(key, data=pred[key], compression='gzip')
        f.attrs['fs'] = pred['fs']
        f.attrs['pred_rr_bpm'] = float(pred['pred_rr_bpm'])
        for key, value in attrs.items():
            f.attrs[key] = value
    temp.replace(path)


def build(args):
    from inference_adapter import AirExtractor
    clips, planned = plan_windows(args.workdir)
    splits = load_json(args.workdir / 'splits.json')['subjects']
    if set(splits.values()) - {'train', 'val', 'test'}:
        raise ValueError('Invalid split name')
    if {c['subject'] for c in clips} - set(splits):
        raise ValueError('An approved subject is missing from fixed splits.json')
    if set(splits.values()) != {'train', 'val', 'test'}:
        raise ValueError('All train/val/test splits are required')
    hashes = {}
    for clip in clips:
        previous = hashes.setdefault(clip['video_sha256'], clip['subject'])
        if previous != clip['subject']:
            raise ValueError('Identical video bytes occur under different infants')
    provenance = load_json(args.provenance) if args.provenance else {'status': 'unknown'}
    checkpoint_hash = digest(args.checkpoint)
    if provenance.get('status') == 'known' and provenance.get('checkpoint_sha256') != checkpoint_hash:
        raise ValueError('Provenance must identify this exact checkpoint_sha256')
    if provenance.get('status') == 'known' and not provenance.get('evidence', '').strip():
        raise ValueError('Known provenance requires a reference to complete training records in evidence')
    evaluation_valid = check_provenance(provenance, splits, args.allow_unknown_extractor_training)
    dest = args.dest.resolve()
    if dest.exists():
        raise ValueError('Build destination already exists; choose a new --dest. Inference cache will be reused.')
    extractor = AirExtractor(args.repo, args.config, args.checkpoint)
    receipt = extractor.receipt
    signature = receipt_signature(receipt)
    cache = args.workdir / 'cache' / signature
    cache.mkdir(parents=True, exist_ok=True)
    save_json(cache / 'extractor.json', receipt)
    rows, rejected = [], []
    arrays = {'train': [], 'val': [], 'test': []}
    for i, (clip, start) in enumerate(planned, 1):
        path = cache / f"{clip['video_sha256']}_{start:06d}.hdf5"
        try:
            if path.exists():
                with h5py.File(path, 'r') as f:
                    if f.attrs.get('extractor_signature') != signature or f.attrs.get('video_sha256') != clip['video_sha256']:
                        raise ValueError('Cache signature differs')
                    x = np.asarray(f['x_10hz'], dtype=np.float32)
                    if x.shape != (300,) or not np.isfinite(x).all():
                        raise ValueError('Corrupt cached waveform')
            else:
                pred = extractor.predict_video(clip['video'], start)
                save_prediction(path, pred, {'extractor_signature': signature, 'video_sha256': clip['video_sha256'],
                                             'start_sec': start, 'clip_id': clip['id']})
                x = pred['x_10hz']
            split = splits[clip['subject']]
            arrays[split].append(x[None, :])
            rows.append({'split': split, 'array_index': len(arrays[split])-1, 'subject': clip['subject'],
                         'clip': clip['id'], 'start_sec': start, 'end_sec': start+30,
                         'video_sha256': clip['video_sha256'], 'label_sha256': clip['label_sha256'],
                         'prediction_hdf5': str(path.resolve()), 'rms_unscaled': float(np.sqrt(np.mean(x.astype(float)**2))),
                         'ptp_unscaled': float(np.ptp(x))})
        except (ValueError, RuntimeError, OSError) as e:
            rejected.append({'clip': clip['id'], 'start_sec': start, 'reason': str(e)})
        print(f'Window {i}/{len(planned)}; accepted={len(rows)} rejected={len(rejected)}', flush=True)
    counts = {k: len(v) for k, v in arrays.items()}
    save_json(args.workdir / 'last_build_attempt.json', {'counts': counts, 'rejected': rejected})
    if not all(counts.values()):
        raise ValueError(f'Empty split after exclusions: {counts}. See last_build_attempt.json')
    arrays = {k: np.stack(v).astype(np.float32) for k, v in arrays.items()}
    stats = fit_scaler(arrays['train'])
    stats['extractor_signature'] = signature
    dest.mkdir(parents=True)
    for split, data in arrays.items():
        np.save(dest / f'X_{split}_unscaled.npy', data, allow_pickle=False)
        np.save(dest / f'X_{split}.npy', normalize(data, stats), allow_pickle=False)
    save_json(dest / 'normalization.json', stats)
    save_json(dest / 'windows.json', rows)
    save_json(dest / 'splits.json', {'subjects': splits})
    save_json(dest / 'extractor.json', receipt)
    save_json(dest / 'approvals.json', load_json(args.workdir / 'approvals.json'))
    save_json(dest / 'manifest.json', load_json(args.workdir / 'manifest.json'))
    save_json(dest / 'build_report.json', {'counts': counts, 'shape': '(N,1,300)', 'fs': 10,
              'window_seconds': 30, 'stride_seconds': 5, 'extractor_signature': signature,
              'pipeline_sha256': digest(__file__), 'rejected': rejected, 'provenance': provenance,
              'heldout_extractor_subjects_verified': evaluation_valid,
              'limitation': 'Normal-only splits do not measure sensitivity to actual abnormal breathing.'})
    print(f'Dataset saved: {dest}; {counts}')


def predict(args):
    from inference_adapter import AirExtractor
    extractor = AirExtractor(args.repo, args.config, args.checkpoint)
    signature = receipt_signature(extractor.receipt)
    if args.out.exists():
        raise ValueError('Prediction output directory exists; choose a new --out')
    pred = extractor.predict_video(args.video, args.start)
    args.out.mkdir(parents=True)
    save_prediction(args.out / 'prediction.hdf5', pred, {'extractor_signature': signature, 'start_sec': args.start})
    save_json(args.out / 'extractor.json', extractor.receipt)
    np.save(args.out / 'input_unscaled.npy', pred['x_10hz'][None, None, :], allow_pickle=False)
    if args.scaler:
        stats = load_json(args.scaler)
        if stats.get('extractor_signature') != signature:
            raise ValueError('Normalizer belongs to a different extractor configuration/checkpoint/source')
        np.save(args.out / 'input.npy', normalize(pred['x_10hz'][None, None, :], stats), allow_pickle=False)
    print(f'Inference completed; (1,1,300) saved to {args.out}. No normal/abnormal label assigned.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    command = sub.add_parser('scan', help='Inspect actual files and create human review pages')
    command.add_argument('--air125', type=Path)
    command.add_argument('--air400', type=Path)
    command.add_argument('--out', type=Path, required=True)
    command.add_argument('--label-key', default='respiration')
    command.add_argument('--time-key', help='Explicit HDF5 seconds key; no guessing of units')
    command.add_argument('--label-fs', type=float)
    command.add_argument('--refresh-unreviewed', action='store_true', help='Rescan only if no human approvals exist')
    command.set_defaults(action=scan)
    command = sub.add_parser('approve', help='Explicitly approve manually reviewed normal intervals')
    command.add_argument('--workdir', type=Path, required=True)
    command.add_argument('--clip', required=True)
    command.add_argument('--normal', type=float, nargs=2, action='append', required=True, metavar=('START','END'))
    command.add_argument('--reviewer', required=True)
    command.add_argument('--notes', default='')
    for flag in ('video-reviewed','label-reviewed','alignment-confirmed','quality-acceptable'):
        command.add_argument('--'+flag, action='store_true', required=True)
    command.set_defaults(action=approve)
    command = sub.add_parser('split', help='Fix a subject-wise 70/15/15 allocation (rounded by subjects)')
    command.add_argument('--workdir', type=Path, required=True)
    command.add_argument('--seed', type=int, default=100)
    command.set_defaults(action=split_command)
    for name, action in [('build', build), ('predict', predict)]:
        command = sub.add_parser(name)
        command.add_argument('--repo', type=Path, default=Path(r'C:\Users\OHS\air-400'))
        command.add_argument('--config', type=Path, required=True)
        command.add_argument('--checkpoint', type=Path, required=True)
        command.set_defaults(action=action)
        if name == 'build':
            command.add_argument('--workdir', type=Path, required=True)
            command.add_argument('--dest', type=Path, required=True)
            command.add_argument('--provenance', type=Path)
            command.add_argument('--allow-unknown-extractor-training', action='store_true')
        else:
            command.add_argument('--video', type=Path, required=True)
            command.add_argument('--start', type=float, default=0)
            command.add_argument('--out', type=Path, required=True)
            command.add_argument('--scaler', type=Path)
    args = parser.parse_args()
    if getattr(args, 'time_key', None) and getattr(args, 'label_fs', None):
        parser.error('Choose --time-key or --label-fs, not both')
    try:
        args.action(args)
    except (ValueError, RuntimeError, OSError, KeyError) as e:
        parser.exit(2, f'Error: {e}\n')


if __name__ == '__main__':
    main()
