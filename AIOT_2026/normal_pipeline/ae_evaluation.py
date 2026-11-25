"""Label-aware AE evaluation; normal-only accuracy is not anomaly recall."""
import numpy as np
import re


def validate_feature_records(records, *, allow_assumed):
    groups,sources,ids={},{},set()
    if not records or type(allow_assumed) is not bool:
        raise ValueError('구간과 명시적 정상 가정 사용 여부가 필요합니다.')
    for r in records:
        if r['id'] in ids:
            raise ValueError('중복 구간 ID')
        ids.add(r['id'])
        group,split,label=r['group_id'],r['split'],r['label']
        if ':' not in group or split not in ('train','valid','test') or type(r['reviewed']) is not bool:
            raise ValueError('전체 영아 ID/split/검토 bool 형식 오류')
        if label not in ('normal_assumed','normal_reviewed_motion','static_simulation'):
            raise ValueError('라벨 오류')
        if label=='normal_assumed' and not allow_assumed:
            raise ValueError('미검토 정상 가정 자료 사용 승인이 없습니다.')
        if label=='normal_reviewed_motion' and r['reviewed'] is not True:
            raise ValueError('검토 완료로 표시할 수 없습니다.')
        if split=='train' and label=='static_simulation':
            raise ValueError('정지 인형을 정상 복원 대상으로 학습할 수 없습니다.')
        digest=r['source_sha256']
        if not re.fullmatch('[0-9a-f]{64}',digest):
            raise ValueError('원본 SHA-256 오류')
        if groups.setdefault(group,split)!=split or sources.setdefault(digest,split)!=split:
            raise ValueError('동일 영아/원본의 분할 누수')


def _inputs(scores, abnormal):
    scores=np.asarray(scores,dtype=np.float64).reshape(-1)
    labels=np.asarray(abnormal)
    if (labels.dtype != np.bool_ or labels.ndim!=1 or labels.shape!=scores.shape
            or not scores.size or not np.isfinite(scores).all()):
        raise ValueError('유한한 점수와 실제 bool 라벨이 필요합니다.')
    return scores,labels


def classification_metrics(scores, abnormal, threshold):
    scores,labels=_inputs(scores,abnormal)
    if not np.isfinite(threshold):
        raise ValueError('유한한 임계값이 필요합니다.')
    pred=scores>threshold
    normal=~labels
    tp=int(np.sum(pred & labels));fp=int(np.sum(pred & normal))
    fn=int(np.sum(~pred & labels));tn=int(np.sum(~pred & normal))
    recall=tp/(tp+fn) if tp+fn else None
    specificity=tn/(tn+fp) if tn+fp else None
    return dict(normal_count=int(normal.sum()),abnormal_count=int(labels.sum()),
                tp=tp,fp=fp,tn=tn,fn=fn,recall=recall,
                false_positive_rate=1-specificity if specificity is not None else None,
                specificity=specificity,accuracy=float(np.mean(pred==labels)),
                balanced_accuracy=(recall+specificity)/2 if recall is not None and specificity is not None else None)


def select_threshold(scores, abnormal, max_fpr=.05):
    scores,labels=_inputs(scores,abnormal)
    if not labels.any() or labels.all() or not 0<=max_fpr<=1:
        raise ValueError('정상과 이상 모사 검증 라벨이 모두 필요합니다.')
    unique=np.unique(scores)
    margin=max(1e-6,float(np.max(np.abs(unique)))*1e-5)
    candidates=np.r_[unique[0]-margin,(unique[:-1]+unique[1:])/2,unique[-1]+margin]
    choices=[]
    for threshold in candidates:
        result=classification_metrics(scores,labels,float(threshold))
        if result['false_positive_rate']<=max_fpr:
            choices.append(((result['balanced_accuracy'],-result['false_positive_rate'],float(threshold)),result))
    key,result=max(choices,key=lambda x:x[0])
    return key[2],result


def normal_train_statistics(waves,bpms,splits,abnormal):
    waves=np.asarray(waves,dtype=np.float32);bpms=np.asarray(bpms,dtype=np.float32).reshape(-1,1)
    labels=np.asarray(abnormal)
    if labels.dtype!=np.bool_ or len(waves)!=len(bpms) or len(labels)!=len(waves) or len(splits)!=len(waves):
        raise ValueError('학습 배열/라벨 길이 또는 bool 형식 오류')
    mask=(np.asarray(splits)=='train') & ~labels
    if not mask.any():
        raise ValueError('정상 학습 자료가 없습니다.')
    x,b=waves[mask],bpms[mask]
    if not np.isfinite(x).all() or not np.isfinite(b).all() or x.std()==0:
        raise ValueError('정상 학습 값이 유효하지 않습니다.')
    return dict(wave_mean=float(x.mean(dtype=np.float64)),wave_std=float(x.std(dtype=np.float64)),
                bpm_mean=float(b.mean(dtype=np.float64)),bpm_std=max(float(b.std(dtype=np.float64)),1.))
