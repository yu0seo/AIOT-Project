"""Experimental pixel-motion evidence. No per-clip amplitude normalization."""
import math

import cv2
import numpy as np
from scipy import signal

from .manual_roi import roi_box


def motion_features(frames, normalized_roi, fs=15):
    """Measure 4x4 patch trajectories after median background translation removal.

    Units are pixels at the supplied resolution, not physical chest displacement.
    Rotation, parallax, occlusion and nonrespiratory local movement remain limitations.
    candidate_bpm is diagnostic only; presence logic must approve it separately.
    """
    frames = np.asarray(frames)
    if (not isinstance(fs, (int, float)) or not math.isfinite(fs) or fs <= 0
            or frames.ndim != 4 or frames.shape[-1] != 3 or len(frames) < fs * 10
            or not np.isfinite(frames).all() or frames.min() < 0 or frames.max() > 255):
        raise ValueError('10초 이상의 유한한 RGB [0,255] 영상과 양수 FPS가 필요합니다.')
    n, h, w, _ = frames.shape
    x, y, rw, rh = roi_box(normalized_roi, h, w)
    x0, y0, x1, y1 = int(x), int(y), int(x+rw), int(y+rh)
    if min(x1-x0, y1-y0) < 16:
        raise ValueError('ROI가 너무 작습니다.')
    gray = np.stack([cv2.cvtColor(f.astype(np.uint8), cv2.COLOR_RGB2GRAY) for f in frames])
    first = gray[0]
    grad = np.hypot(cv2.Sobel(first, cv2.CV_32F, 1, 0), cv2.Sobel(first, cv2.CV_32F, 0, 1))
    bg = np.ones((h, w), bool)
    margin = 4
    bg[max(0,y0-margin):min(h,y1+margin), max(0,x0-margin):min(w,x1+margin)] = False
    bg &= grad > 3
    edges_x, edges_y = np.linspace(x0, x1, 5).astype(int), np.linspace(y0, y1, 5).astype(int)
    velocity, background = [], []
    for previous, current in zip(gray[:-1], gray[1:]):
        flow = cv2.calcOpticalFlowFarneback(previous, current, None, .5, 3, 15, 3, 5, 1.2, 0)
        shift = np.median(flow[bg], axis=0) if bg.sum() >= 40 else np.zeros(2)
        background.append(shift)
        velocity.append([np.median(flow[ya:yb, xa:xb], axis=(0, 1))-shift
                         for ya, yb in zip(edges_y[:-1], edges_y[1:])
                         for xa, xb in zip(edges_x[:-1], edges_x[1:])])
    velocity, background = np.asarray(velocity), np.asarray(background)
    trajectories = signal.detrend(np.concatenate([np.zeros((1,16,2)), np.cumsum(velocity, axis=0)]), axis=0)
    flattened = trajectories.reshape(n, -1)
    # Projection retains pixel units: the principal direction has unit Euclidean norm.
    _, _, axes = np.linalg.svd(flattened, full_matrices=False)
    waveform = flattened @ axes[0] / np.sqrt(16)
    amplitude = float(waveform.std())
    frequencies, power = signal.periodogram(waveform, fs=fs)
    respiratory = (frequencies >= .2) & (frequencies <= 1.5)
    total = float(power[frequencies > 0].sum())
    peak = int(np.flatnonzero(respiratory)[np.argmax(power[respiratory])])
    peak_band = np.abs(frequencies-frequencies[peak]) <= max(.06, fs/n)
    concentration = float(power[peak_band].sum()/total) if total > 1e-12 else 0.
    energy_fraction = float(power[respiratory].sum()/total) if total > 1e-12 else 0.
    projected = np.sum(trajectories * axes[0].reshape(1,16,2), axis=2)
    usable = projected.std(axis=0) > .01
    correlations = [abs(float(np.corrcoef(projected[:,i], waveform)[0,1]))
                    for i in np.flatnonzero(usable)] if amplitude > 1e-8 else []
    coherence = float(np.mean(np.asarray(correlations) >= .6)) if correlations else 0.
    texture = float(grad[y0:y1,x0:x1].mean())
    pixel_change = float(np.abs(np.diff(gray.astype(np.float32), axis=0)).mean())
    camera_p95 = float(np.percentile(np.linalg.norm(background, axis=1), 95))
    clipped = float(np.mean((gray[:,y0:y1,x0:x1] <= 2) | (gray[:,y0:y1,x0:x1] >= 253)))
    reasons = []
    if pixel_change < 1e-5:
        reasons.append('frozen')
    if texture < 1.5:
        reasons.append('insufficient_texture')
    if bg.sum() < 40:
        reasons.append('insufficient_background')
    # Background subtraction leaves texture-dependent residual flow. Reject active
    # camera movement rather than treating that residual as a respiratory signal.
    if camera_p95 > .1:
        reasons.append('excessive_camera_motion')
    if clipped > .7:
        reasons.append('under_or_overexposed')
    return dict(quality_ok=not reasons, quality_reasons=reasons, amplitude_px=amplitude,
                candidate_bpm=float(frequencies[peak]*60) if total > 1e-12 else None,
                periodic_concentration=concentration, respiratory_energy_fraction=energy_fraction,
                spatial_coherence=coherence, texture=texture, camera_motion_p95_px=camera_p95,
                mean_pixel_change=pixel_change, clipped_fraction=clipped,
                waveform=waveform.astype(np.float32), background_velocity=background.astype(np.float32),
                patch_trajectories=trajectories.astype(np.float32), fs=float(fs),
                method='farneback_bg_translation_v2', frame_size=[w,h])
