"""Experimental teacher-preserving fine-tuning. No production model replacement."""
import numpy as np
import torch

from .no_motion import preservation_loss


def freeze_teacher(model):
    model.eval()
    for p in model.parameters():
        p.requires_grad_(False)
    return model


def preservation_metrics(pred, reference):
    pred, reference = (np.asarray(x, dtype=np.float64).reshape(-1) for x in (pred, reference))
    if pred.shape != reference.shape or not pred.size or not np.isfinite([pred, reference]).all():
        raise ValueError('출력과 목표가 유효하지 않습니다.')
    mse = float(np.mean((pred-reference)**2))
    corr = None if min(pred.std(), reference.std()) < 1e-8 else float(np.corrcoef(pred, reference)[0,1])
    return dict(mse=mse, relative_mse=mse/max(float(np.var(reference)),1e-8),
                correlation=corr, raw_energy=float(np.mean(pred**2)), raw_std=float(np.std(pred)))


def train_epoch(student, cases, optimizer, device, batch_size, still_weight):
    # eval disables dropout but permits gradients. This matches deterministic
    # production inference; only the student is passed to the optimizer.
    student.eval()
    counts = {flag: sum((c['kind']=='breathing_candidate') == flag for c in cases) for flag in (True,False)}
    if min(counts.values()) == 0 or batch_size < 1:
        raise ValueError('호흡/정지 학습 입력과 양수 배치 크기가 필요합니다.')
    optimizer.zero_grad(set_to_none=True)
    objective = 0.
    for case in cases:
        breathing = case['kind']=='breathing_candidate'
        inputs, target = case['inputs'], case['target_raw']
        for start in range(0, len(inputs), batch_size):
            end = min(start+batch_size, len(inputs))
            x = torch.from_numpy(inputs[start:end]).to(device)
            y = torch.from_numpy(target[start:end]).to(device)
            pred = student(x).flatten()
            zero = torch.zeros_like(pred)
            # Accumulate the exact mean over each sequence, including the last
            # partial batch, then balance cases within each input category.
            loss = (preservation_loss(pred,y,zero,still_weight) if breathing
                    else preservation_loss(zero,zero,pred,still_weight))
            loss = loss*((end-start)/len(inputs))/counts[breathing]
            loss.backward()
            objective += float(loss.detach())
    for p in student.parameters():
        if p.grad is not None and not torch.isfinite(p.grad).all():
            raise ValueError('student gradient가 유한하지 않습니다.')
    optimizer.step()
    return objective
