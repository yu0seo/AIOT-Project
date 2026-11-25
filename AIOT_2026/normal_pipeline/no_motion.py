"""Isolated preparation and loss primitives for the no-motion experiment."""
import hashlib
import math
import re
from collections import Counter
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    with Path(path).open('rb') as fp:
        return hashlib.file_digest(fp, 'sha256').hexdigest()


def preservation_loss(pred_breath, teacher_target, pred_still, still_weight):
    """Preserve teacher raw output; penalize absolute static raw energy.

    Inputs must be unnormalized network predictions. Teacher values are detached.
    No per-window standardization or spectral normalization is applied here.
    """
    if isinstance(still_weight, bool) or not math.isfinite(still_weight) or still_weight <= 0:
        raise ValueError('정지 손실 가중치는 유한한 양수여야 합니다.')
    for value in (pred_breath, teacher_target, pred_still):
        if (not torch.is_floating_point(value) or not value.numel()
                or not torch.isfinite(value).all()):
            raise ValueError('손실 입력은 비어 있지 않은 유한 실수 텐서여야 합니다.')
    if pred_breath.shape != teacher_target.shape:
        raise ValueError('정상 출력과 teacher 목표 shape가 다릅니다.')
    return ((pred_breath-teacher_target.detach()).square().mean()
            + still_weight*pred_still.square().mean())


def validate_records(records, *, require_approved, verify_files=True, root=ROOT):
    if not records:
        raise ValueError('검사할 구간이 없습니다.')
    subjects, sources, ids = {}, {}, set()
    counts = Counter()
    hashes = {}
    for row in records:
        ident = row['id']
        if ident in ids:
            raise ValueError(f'중복 구간 ID: {ident}')
        ids.add(ident)
        group, split = row['group_id'], row['split']
        if ':' not in group or split not in ('train', 'valid', 'test'):
            raise ValueError(f'전체 그룹 ID 또는 split 오류: {ident}')
        if row['kind'] not in ('breathing_candidate', 'static_real', 'static_synthetic'):
            raise ValueError(f'알 수 없는 데이터 종류: {ident}')
        start, end = row['start_sec'], row['end_sec']
        if (type(start) not in (int, float) or type(end) not in (int, float)
                or not math.isfinite(start) or not math.isfinite(end)
                or start < 0 or end-start != 30):
            raise ValueError(f'정확한 30초 구간이 아닙니다: {ident}')
        review = row['review']
        if type(review['approved']) is not bool:
            raise ValueError(f'approved는 JSON true/false여야 합니다: {ident}')
        if review['approved'] and (not str(review.get('reviewer', '')).strip()
                                   or not str(review.get('notes', '')).strip()):
            raise ValueError(f'승인자와 검토 근거가 필요합니다: {ident}')
        if require_approved and not review['approved']:
            raise ValueError(f'미검토 구간은 학습할 수 없습니다: {ident}')
        digest = row['source_sha256']
        if not re.fullmatch('[0-9a-f]{64}', digest):
            raise ValueError(f'SHA-256 오류: {ident}')
        if 'manual_roi' in row:
            from .manual_roi import roi_box
            annotation=row['manual_roi']
            if (row['kind']!='static_real' or not isinstance(annotation,dict)
                    or annotation.get('source_sha256')!=digest or not annotation.get('reason')):
                raise ValueError(f'수동 ROI는 원본 해시에 연결된 실제 정지 시험용이어야 합니다: {ident}')
            roi_box(annotation['box_xywh_normalized'],1,1)
        if subjects.setdefault(group, split) != split or sources.setdefault(digest, split) != split:
            raise ValueError(f'동일 영아/원본의 split 누수: {ident}')
        if verify_files:
            path = (Path(root)/row['source']).resolve()
            if path not in hashes:
                hashes[path] = sha256(path)
            if hashes[path] != digest:
                raise ValueError(f'원본 해시 불일치: {ident}')
        counts['approved' if review['approved'] else 'pending_review'] += 1
        counts[f'{split}:{row["kind"]}'] += 1
    return dict(counts)
