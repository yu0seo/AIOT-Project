"""One 30-second RGB-buffer API shared by dataset construction and deployment.

Imports the user's existing AIR code without changing it. Derived configuration
changes only CHUNK_LENGTH to FRAME_DEPTH so 10Hz/30s buffers lose no tail frames.
"""
from __future__ import annotations

import importlib.util
from importlib.metadata import version
import logging
import os
from pathlib import Path
import sys

import numpy as np
import yaml

from pipeline import digest, normalize, receipt_signature, to_10hz


def read_video_info(path):
    import cv2
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise ValueError(f'Cannot open video: {path}')
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if not np.isfinite(fps) or fps <= 0 or n <= 0:
            raise ValueError(f'Invalid video FPS/frame count: {path}')
        return {'fps': fps, 'frames': n, 'duration': n / fps}
    finally:
        cap.release()


def read_rgb_window(path, start, seconds=30):
    """Read by frame index, no lossy re-encoding or whole-video normalization."""
    import cv2
    info = read_video_info(path)
    fps = info['fps']
    if abs(fps - round(fps)) > 1e-3:
        raise ValueError(f'Non-integer FPS {fps}: timestamp-aware capture is required; no silent rounding')
    fs = int(round(fps))
    if not np.isfinite(start) or abs(start * fs - round(start * fs)) > 1e-6:
        raise ValueError('Window start must fall on an actual frame timestamp')
    first, count = int(round(start * fs)), int(round(seconds * fs))
    if first < 0 or first + count > info['frames']:
        raise ValueError('Video shorter than requested window')
    cap = cv2.VideoCapture(str(path))
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, first)
        if abs(cap.get(cv2.CAP_PROP_POS_FRAMES) - first) > .5:
            raise ValueError('Decoder did not seek to the requested frame')
        frames = []
        for _ in range(count):
            ok, bgr = cap.read()
            if not ok:
                raise ValueError('Decoder stopped before the full window; excluded')
            frames.append(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        return np.asarray(frames), fs
    finally:
        cap.release()


class AirExtractor:
    def __init__(self, repo, config, checkpoint):
        self.repo = Path(repo).resolve()
        self.checkpoint = Path(checkpoint).resolve()
        self.config = yaml.safe_load(Path(config).read_text(encoding='utf-8-sig'))
        cfg = self.config
        self.data = cfg['TEST']['DATA'][0] if isinstance(cfg['TEST']['DATA'], list) else cfg['TEST']['DATA']
        pre = self.data['PREPROCESS']
        if cfg['MODEL']['NAME'] != 'DeepPhys' or self.data['DATA_FORMAT'] != 'NDCHW' or not self.data['INFANT_FLAG']:
            raise ValueError('This adapter requires DeepPhys, NDCHW, INFANT_FLAG=True')
        if pre.get('DO_AUGMENTATION') or pre.get('OF_RESAMPLE_FS', 0):
            raise ValueError('Augmentation/OF frame resampling is incompatible with exact deployment timestamps')
        if pre.get('OF_METHOD') == 'coarse2fine':
            raise ValueError('Use the existing Windows-compatible DeepFlow configuration')
        self.config_changes = {'CHUNK_LENGTH': {'original': pre.get('CHUNK_LENGTH'), 'effective': cfg['MODEL']['FRAME_DEPTH']},
                               'DO_CHUNK': {'original': pre.get('DO_CHUNK'), 'effective': True}}
        pre['DO_CHUNK'] = True
        pre['CHUNK_LENGTH'] = int(cfg['MODEL']['FRAME_DEPTH'])
        for key in ('BODY_DETECTOR_PATH', 'FACE_DETECTOR_PATH'):
            p = Path(cfg['DATA_PATH'][key])
            cfg['DATA_PATH'][key] = str((self.repo / p).resolve() if not p.is_absolute() else p.resolve())
            if not Path(cfg['DATA_PATH'][key]).is_file():
                raise FileNotFoundError(cfg['DATA_PATH'][key])
        # The upstream inference truncates each batch by GPU-count * frame-depth.
        # Fixing the visible GPU count avoids sample loss and DataParallel hooks.
        os.environ.setdefault('CUDA_VISIBLE_DEVICES', '0')
        os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG', ':4096:8')
        os.environ.setdefault('MPLBACKEND', 'Agg')
        os.environ.setdefault('YOLO_CONFIG_DIR', str(Path.cwd() / 'work' / 'air_runtime'))
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(self.repo))
        spec = importlib.util.spec_from_file_location('air_upstream_infer', self.repo / 'infer.py')
        self.upstream = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.upstream)
        import torch
        if torch.cuda.device_count() > 1:
            raise ValueError('Launch with CUDA_VISIBLE_DEVICES=0 (exactly one visible GPU)')
        self.torch = torch
        self.logger = logging.getLogger('air_pipeline')
        self.model = self.upstream.build_model(cfg, self.logger)
        self.model.load_state_dict(torch.load(self.checkpoint, map_location='cpu', weights_only=True))
        from processors.pre_processor import PreProcessor
        self.preprocessor = PreProcessor(pre, cfg['DATA_PATH']['BODY_DETECTOR_PATH'], cfg['DATA_PATH']['FACE_DETECTOR_PATH'])
        sources = [self.repo / 'infer.py', self.repo / 'main.py']
        for folder in ('dataloaders', 'processors', 'models', 'trainers', 'loss'):
            sources.extend(sorted((self.repo / folder).glob('*.py')))
        self.receipt = {'config': cfg, 'config_changes': self.config_changes,
                        'checkpoint_sha256': digest(self.checkpoint),
                        'source_sha256': {p.relative_to(self.repo).as_posix(): digest(p) for p in sources},
                        'detectors_sha256': {k: digest(cfg['DATA_PATH'][k]) for k in ('BODY_DETECTOR_PATH','FACE_DETECTOR_PATH')},
                        'adapter_sha256': digest(__file__),
                        'pipeline_sha256': digest(to_10hz.__code__.co_filename),
                        'versions': {name: version(name) for name in ('torch', 'numpy', 'scipy', 'opencv-contrib-python', 'ultralytics')},
                        'device': 'cuda' if torch.cuda.is_available() else 'cpu',
                        'contract': 'RGB uint8, integer fs >=10, exactly 30s, independent buffers; update every 5s; upstream filtered respiration; polyphase 10Hz'}

    def predict_rgb(self, frames, fs, timestamps=None):
        """Return raw model output, filtered waveform and unscaled 10Hz input.

        Production capture must provide all 30s frames at uniform fs. Pass real
        timestamps to reject missing/irregular frames rather than filling gaps.
        """
        from torch.utils.data import DataLoader
        frames = np.asarray(frames)
        if frames.ndim != 4 or frames.shape[-1] != 3 or frames.dtype != np.uint8:
            raise ValueError('Expected RGB uint8 array (T,H,W,3)')
        if fs < 10 or int(fs) != fs or len(frames) != fs * 30:
            raise ValueError('Expected a complete 30s buffer at integer fs >=10')
        if timestamps is not None:
            ts = np.asarray(timestamps, dtype=np.float64)
            if (ts.shape != (len(frames),) or not np.isfinite(ts).all()
                    or not np.allclose(np.diff(ts), 1/fs, rtol=.05, atol=.001)
                    or np.max(np.abs(ts - ts[0] - np.arange(len(ts))/fs)) > .25/fs):
                raise ValueError('Frame timing gap/irregular sampling: judgement unavailable')
        self.upstream.set_random_seeds(100)
        clips, _ = self.preprocessor.preprocess(frames, np.zeros(len(frames), dtype=np.float32), fs)
        if clips.ndim != 5 or clips.shape[0] * clips.shape[1] != len(frames):
            raise ValueError('PreProcessor dropped frames; do not stretch its output')
        dataset = self.upstream.InferenceDataset.__new__(self.upstream.InferenceDataset)
        dataset.frames_clips = clips
        dataset.infant_flag = True
        dataset.fs = fs
        dataset.data_format = 'NDCHW'
        loader = DataLoader(dataset, batch_size=self.config['INFERENCE']['BATCH_SIZE'], shuffle=False, num_workers=0)
        raw = []
        handle = self.model.register_forward_hook(lambda module, inp, out: raw.append(out.detach().cpu().numpy().reshape(-1)))
        try:
            metrics = self.upstream.run_inference(self.config, self.model, loader, self.logger)
        finally:
            handle.remove()
        raw = np.concatenate(raw)
        respiration = np.asarray(metrics['pred_seq']).reshape(-1)
        if len(raw) != len(frames):
            raise ValueError('Upstream inference dropped frames; no padding allowed')
        x = to_10hz(respiration, metrics['fs'])
        if not np.isfinite(raw).all():
            raise ValueError('Non-finite raw model output')
        return {'raw_model': raw.astype(np.float32), 'respiration': respiration.astype(np.float32),
                'time_sec': np.arange(len(raw), dtype=np.float64)/fs, 'fs': fs,
                'x_10hz': x, 'pred_rr_bpm': metrics['pred_rr_bpm']}

    def predict_video(self, path, start=0):
        frames, fs = read_rgb_window(path, start)
        return self.predict_rgb(frames, fs)

    def model_input(self, frames, fs, scaler, timestamps):
        """Deployment API: normalized (1,1,300), plus raw diagnostics."""
        if scaler.get('extractor_signature') != receipt_signature(self.receipt):
            raise ValueError('Normalizer belongs to a different extractor configuration/checkpoint/source')
        prediction = self.predict_rgb(frames, fs, timestamps=timestamps)
        return normalize(prediction['x_10hz'][None, None, :], scaler), prediction
