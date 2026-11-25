"""Cache approved videos through the production preprocessor, without training."""
import json
import os
import sys
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import torch

from .no_motion import ROOT, sha256, validate_records
from .manual_roi import manual_roi_override


def frozen_frames(frames):
    if frames.ndim != 4 or frames.shape[0] != 450 or frames.shape[-1] != 3:
        raise ValueError('정확한 450프레임 RGB 입력이 필요합니다.')
    return np.repeat(frames[:1], 450, axis=0)


def encode_inputs(frames, runner, manual_box=None, on_box=None):
    if frames.ndim != 4 or frames.shape[0] != 450 or frames.shape[-1] != 3:
        raise ValueError('정확한 450프레임 RGB 입력이 필요합니다.')
    with manual_roi_override(runner.pre,manual_box,on_box):
        clips, _ = runner.pre.preprocess(frames, np.zeros(450, dtype=np.float32), 15)
    if (clips.ndim != 5 or clips.shape[:2] != (1, 450) or clips.shape[-1] != 6
            or not np.isfinite(clips).all()):
        raise ValueError('생산 전처리 결과가 유한한 (1,450,H,W,6)이 아닙니다.')
    return np.ascontiguousarray(clips[0].transpose(0, 3, 1, 2), dtype=np.float32)


@torch.inference_mode()
def raw_prediction(inputs, runner):
    # Same frame ordering and batch size as DeepPhysRunner.extract. Constant outputs
    # are retained here because a static control is intended to have zero variation.
    if runner.model.training:
        raise ValueError('teacher는 eval 상태여야 합니다.')
    pred = []
    for i in range(0, len(inputs), runner.batch_size):
        batch = torch.from_numpy(inputs[i:i+runner.batch_size]).to(runner.device)
        pred.append(runner.model(batch).flatten().cpu())
    raw = torch.cat(pred).numpy()
    if raw.shape != (450,) or not np.isfinite(raw).all():
        raise ValueError('teacher raw 출력이 450점의 유한한 값이 아닙니다.')
    return raw


def prepare_cache(manifest, destination):
    from babycam.common import Config, atomic_json
    document = json.loads(manifest.read_text(encoding='utf-8-sig'))
    if document.get('schema') != 1:
        raise ValueError('manifest schema 오류')
    validate_records(document['records'], require_approved=False)
    selected = [r for r in document['records'] if r['review']['approved'] is True]
    validate_records(selected, require_approved=True)
    # A new static-only source can be prepared independently. The trainer,
    # rather than this preprocessing tool, requires breathing + static splits.
    if any(r['start_sec'] != 0 for r in selected):
        raise ValueError('현재 캐시는 승인된 첫 0~30초 구간만 지원합니다.')
    checkpoint = ROOT/document['teacher_checkpoint']
    if sha256(checkpoint) != document['teacher_sha256']:
        raise ValueError('teacher 가중치 해시 불일치')
    if destination.exists():
        raise ValueError('새 --output 폴더를 지정하세요. 기존 캐시는 덮어쓰지 않습니다.')
    cfg = Config.load(ROOT/'.env', require_supabase=False)
    if cfg.root != ROOT:
        raise ValueError('현재 저장소와 .env의 AIR400_ROOT가 다릅니다.')
    tracked = ['models/air400_detect_v2.py', 'models/deep_phys.py',
               'processors/pre_processor.py', 'processors/post_processor.py',
               'configs/inference/deepphys_deep_infer.yaml', 'detectors/yolov8m.pt',
               'detectors/yolov8n-face.pt', 'checkpoints/DeepPhys_Deep_Body_best.pth',
               'output/ae_results_v2/air400_ae.pt']
    hashes = {name: sha256(ROOT/name) for name in tracked}
    hashes['cache_source'] = sha256(__file__)
    destination.mkdir(parents=True, exist_ok=False)
    os.environ['YOLO_CONFIG_DIR'] = str(destination/'ultralytics')
    sys.path.insert(0, str(ROOT/'models'))
    import air400_detect_v2 as existing
    args = SimpleNamespace(air400_root=ROOT, config=None, deepphys_ckpt=checkpoint,
                           body_detector=ROOT/'detectors/yolov8m.pt',
                           face_detector=ROOT/'detectors/yolov8n-face.pt',
                           no_roi=False, frame_batch=16)
    runner = existing.DeepPhysRunner(args, torch.device('cuda' if torch.cuda.is_available() else 'cpu'))
    roi_trace = []
    original_roi = runner.pre.get_roi_box

    def traced_roi(frames):
        box, detections = original_roi(frames)
        roi_trace.append([float(v) for v in box])
        return box, detections

    runner.pre.get_roi_box = traced_roi
    for parameter in runner.model.parameters():
        parameter.requires_grad_(False)
    report = dict(schema=1, manifest_sha256=sha256(manifest), pipeline_hashes=hashes,
                  teacher_sha256=document['teacher_sha256'], video_fs=15, samples=450,
                  frame_batch=16, roi=True, cases=[], skipped_unreviewed=len(document['records'])-len(selected))
    atomic_json(destination/'cache.json', report, indent=2)

    def save_case(record, frames):
        result = dict(record)
        print('PREPARE', record['id'], record['kind'], flush=True)
        try:
            roi_trace.clear()
            manual_box=record.get('manual_roi',{}).get('box_xywh_normalized')
            inputs = encode_inputs(frames, runner, manual_box, roi_trace.append)
            raw = raw_prediction(inputs, runner)
            if record['kind'] == 'breathing_candidate' and raw.min() == raw.max():
                raise ValueError('호흡 후보에서 teacher가 상수 raw 출력을 반환했습니다.')
            # Generated numeric names avoid using manifest IDs as filesystem paths.
            filename = f'{len(report["cases"]):04d}.npz'
            target = raw if record['kind'] == 'breathing_candidate' else np.zeros(450, dtype=np.float32)
            np.savez_compressed(destination/filename, inputs=inputs, teacher_raw=raw,
                                target_raw=target, fs=15, metadata_json=json.dumps(record, ensure_ascii=False))
            result.update(status='prepared', file=filename, file_sha256=sha256(destination/filename),
                          roi_mode='manual_source_locked' if manual_box is not None else 'automatic',
                          input_shape=list(inputs.shape), raw_std=float(raw.std()),
                          raw_energy=float(np.mean(raw**2)))
            if roi_trace:
                result['roi_box_xywh'] = roi_trace[-1]
                crop = runner.pre.crop_infant_boxes(frames[:1], roi_trace[-1])[0]
                preview = f'{len(report["cases"]):04d}_roi.png'
                if not runner.cv2.imwrite(str(destination/preview),
                                          runner.cv2.cvtColor(crop.astype(np.uint8), runner.cv2.COLOR_RGB2BGR)):
                    raise OSError('ROI 이미지 저장 실패')
                result['roi_preview'] = preview
        except (existing.InvalidWindow, ValueError) as exc:
            result.update(status='unscored', reason=str(exc), file=None)
        report['cases'].append(result)
        atomic_json(destination/'cache.json', report, indent=2)
        print('RESULT', record['id'], result['status'], result.get('reason', ''), flush=True)
        return result['status'] == 'prepared'

    for record in selected:
        with closing(existing.frame_windows(ROOT/record['source'], cfg.ffmpeg, runner)) as windows:
            n, frames = next(windows, (0, None))
        if n != 450 or frames is None:
            raise ValueError(f'짧거나 읽을 수 없는 입력: {record["id"]}')
        okay = save_case(record, frames)
        if okay and record['kind'] == 'breathing_candidate':
            derived = dict(record, id=record['id']+'_freeze_first_frame', kind='static_synthetic',
                           parent_id=record['id'], provenance='First decoded/resized frame repeated 450 times; not clinical apnea.')
            derived['review'] = dict(approved=True, reviewer='derived from user-reviewed source',
                                    notes='Deterministic synthetic no-motion control; original group/split retained.')
            save_case(derived, frozen_frames(frames))
    if any(sha256(ROOT/name) != digest for name, digest in hashes.items() if name != 'cache_source'):
        raise ValueError('실행 중 모델/전처리 설정이 변경됐습니다.')
    validate_records(report['cases'], require_approved=True)
    report['complete'] = True
    report['protected_files_unchanged'] = True
    report['prepared'] = sum(r['status'] == 'prepared' for r in report['cases'])
    report['unscored'] = len(report['cases'])-report['prepared']
    report['limitation'] = 'Approved data preparation only; no independent validation or apnea performance claim.'
    atomic_json(destination/'cache.json', report, indent=2)
    return dict(prepared=report['prepared'], unscored=report['unscored'], skipped_unreviewed=report['skipped_unreviewed'])
