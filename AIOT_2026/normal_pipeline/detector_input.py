"""Opt-in RGB video -> BGR ndarray boundary for Ultralytics detectors.

The physiological video path stays RGB. Existing checkpoints/services are not
silently migrated because correcting ROI changes the waveform input distribution.
"""
import numpy as np


class RGBDetectorInput:
    def __init__(self,detector):
        self.detector=detector

    def __call__(self,frame,**kwargs):
        frame=np.asarray(frame)
        if frame.ndim!=3 or frame.shape[-1]!=3 or not np.isfinite(frame).all():
            raise ValueError('검출기에 RGB HWC 3채널이 필요합니다.')
        bgr=np.ascontiguousarray(frame[...,::-1],dtype=np.uint8)
        return self.detector(bgr,**kwargs)


def correct_detector_color(preprocessor):
    for name in ('body_detector','face_detector'):
        detector=getattr(preprocessor,name)
        if detector is not None and not isinstance(detector,RGBDetectorInput):
            setattr(preprocessor,name,RGBDetectorInput(detector))


def verify_roi_contract(checkpoint,body_sha256,color_corrected):
    contract=checkpoint.get('feature_contract',{})
    expected=contract.get('body_detector_sha256',checkpoint.get('feature_pipeline_hashes',{}).get('detectors/yolov8m.pt'))
    expected_color=contract.get('detector_color_corrected',False)
    if type(expected_color) is not bool or type(color_corrected) is not bool:
        raise ValueError('검출기 색상 설정은 bool이어야 합니다.')
    if expected!=body_sha256 or expected_color!=color_corrected:
        raise ValueError('AE 학습 ROI 검출기/색상 경로와 실제 입력이 다릅니다. 해당 경로로 재추출/학습한 AE가 필요합니다.')
