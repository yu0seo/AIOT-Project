"""Explicit fixed-region annotation for source-locked bench experiments."""
import math
from contextlib import contextmanager


def roi_box(normalized, height, width):
    if (len(normalized)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) for v in normalized)
            or height<=0 or width<=0):
        raise ValueError('유한한 정규화 ROI x,y,w,h가 필요합니다.')
    x,y,w,h=normalized
    if x<0 or y<0 or min(w,h)<=0 or x+w>1 or y+h>1 or w*h>=.95:
        raise ValueError('ROI는 화면 안의 부분 영역이어야 합니다. 전체 화면 대체는 허용하지 않습니다.')
    return [x*width,y*height,w*width,h*height]


@contextmanager
def manual_roi_override(preprocessor, normalized, on_box=None):
    if normalized is None:
        yield
        return
    roi_box(normalized,1,1)
    original=preprocessor.get_roi_box

    def annotated(frames):
        box=roi_box(normalized,frames.shape[1],frames.shape[2])
        if on_box is not None:
            on_box(box)
        return box,[]

    preprocessor.get_roi_box=annotated
    try:
        yield
    finally:
        preprocessor.get_roi_box=original
