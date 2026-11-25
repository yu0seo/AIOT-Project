"""Adapters for an isolated, source-locked respiration extraction comparison."""
import json
import importlib.util
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import torch

from .manual_roi import roi_box
from .manual_roi import manual_roi_override
from .no_motion import ROOT, sha256
from .respiration_motion import motion_features


def read_manifest(path):
    doc = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if doc.get('schema') != 1 or not doc.get('records'):
        raise ValueError('schema=1 source-locked records가 필요합니다.')
    ids = set()
    for r in doc['records']:
        if r['id'] in ids or ':' not in r['group_id'] or r['split'] not in ('train','valid','test'):
            raise ValueError('중복 ID 또는 영아/분할 정보 오류')
        ids.add(r['id'])
        if r.get('start_sec') != 0 or r.get('end_sec') != 30:
            raise ValueError('현재 비교는 첫 0~30초만 지원합니다.')
        if sha256(ROOT/r['source']) != r['source_sha256']:
            raise ValueError('원본 해시가 다릅니다: '+r['id'])
        roi_box(r['roi_xywh_normalized'],180,320)
    return doc


def read_first_window(source, ffmpeg, existing):
    decoder = SimpleNamespace(resize=(320,180), cv2=cv2)
    with closing(existing.frame_windows(source, ffmpeg, decoder)) as windows:
        count, frames = next(windows, (0,None))
    if count != 450 or frames is None:
        raise ValueError('30초 미만이거나 읽을 수 없는 영상')
    return frames


def motion_windows(frames, box):
    windows = []
    for start in range(0,301,75):
        feature = motion_features(frames[start:start+150],box,15)
        feature = {k:v for k,v in feature.items() if not isinstance(v,np.ndarray)}
        feature.update(start_sec=start/15,end_sec=(start+150)/15,window_seconds=10.)
        windows.append(feature)
    return windows


@torch.inference_mode()
def efficient_raw(inputs, model, device):
    """Respect FRAME_DEPTH=10 and append one frame for EfficientPhys torch.diff.

    Uses deterministic 180/180/90 temporal batches. This 30s bench contract differs
    from original infer.py which can discard incomplete chunks; it is recorded.
    """
    if (inputs.shape[0] != 450 or inputs.ndim != 4 or inputs.shape[1] != 6
            or model.training or not np.isfinite(inputs).all()):
        raise ValueError('450 NCHW 6채널과 eval 모델이 필요합니다.')
    result = []
    for start in range(0,450,180):
        batch = torch.from_numpy(np.ascontiguousarray(inputs[start:start+180,:3])).to(device)
        batch = torch.cat([batch,batch[-1:]],dim=0)
        result.append(model(batch).flatten().cpu().numpy())
    raw = np.concatenate(result)
    if raw.shape != (450,) or not np.isfinite(raw).all():
        raise ValueError('EfficientPhys 결과가 유효한 450점이 아닙니다.')
    return raw


def summarize_decisions(decisions):
    result, absence_start, previous_end = [], None, None
    for d in decisions:
        d = dict(d,clinical_apnea=None)
        if d['respiration_state'] == 'no_motion_detected':
            if absence_start is None or previous_end is None or d['start_sec'] > previous_end:
                absence_start = d['start_sec']
            d['absence_evidence_seconds'] = d['end_sec']-absence_start
        else:
            absence_start = None
            d['absence_evidence_seconds'] = 0. if d['respiration_state'] == 'motion_present' else None
        previous_end = d['end_sec']
        result.append(d)
    return result


def load_native_pyflow(path):
    path=Path(path).resolve()
    if path.suffix.lower() != '.pyd' or not path.is_file():
        raise ValueError('빌드된 Windows pyflow .pyd 파일이 필요합니다.')
    spec=importlib.util.spec_from_file_location('pyflow',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module,'coarse2fine_flow',None)):
        raise ValueError('Coarse2Fine 함수가 없는 모듈입니다.')
    return module


def efficient_coarse_inputs(frames, runner, box, native):
    """Reuse production crop/standardization/resize with official Coarse2Fine flow.

    Serial frame-pair calculation avoids the original Windows multiprocessing import
    issue; pair order and numeric parameters are those of compute_pyflow().
    """
    from processors.pre_processor import _suppress_pyflow_output
    pre=runner.pre
    original=pre.run_optical_flow

    def coarse(cropped):
        normalized=[np.ascontiguousarray(np.clip(f/255.,0.,1.),dtype=np.float64) for f in cropped]
        params=(pre.pyflow_alpha,pre.pyflow_ratio,pre.pyflow_min_width,
                pre.pyflow_n_outer_FP_iterations,pre.pyflow_n_inner_FP_iterations,
                pre.pyflow_n_SOR_iterations,pre.pyflow_col_type)
        flows=[]
        with _suppress_pyflow_output():
            for previous,current in zip(normalized[:-1],normalized[1:]):
                u,v,_=native.coarse2fine_flow(previous,current,*params)
                flows.append(np.stack([u,v,np.sqrt(u*u+v*v+1e-6)],axis=-1))
        flow=np.stack(flows).astype(np.float32)
        if not np.isfinite(flow).all():
            raise ValueError('Coarse2Fine가 유한하지 않은 flow를 반환했습니다.')
        return np.concatenate([flow,np.zeros_like(flow[:1])],axis=0)

    pre.run_optical_flow=coarse
    try:
        with manual_roi_override(pre,box):
            clips,_=pre.preprocess(frames,np.zeros(450,np.float32),15)
        if clips.shape != (1,450,96,96,6) or not np.isfinite(clips).all():
            raise ValueError('EfficientPhys 전처리 shape 오류')
        return np.ascontiguousarray(clips[0].transpose(0,3,1,2),dtype=np.float32)
    finally:
        pre.run_optical_flow=original
