"""공식 다변량 MiniRocket 변환과 L2 로지스틱 분류기."""
import warnings
from dataclasses import dataclass

import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler


def as_channels_first(windows):
    values = np.asarray(windows, dtype=np.float32)
    if values.ndim != 3 or values.shape[2] != 4 or values.shape[1] < 9 or not len(values):
        raise ValueError('MiniRocket 입력은 비어 있지 않은 (N,T,4), T>=9이어야 합니다.')
    if not np.isfinite(values).all():
        raise ValueError('MiniRocket 입력에 결측값/무한대가 있습니다.')
    return np.ascontiguousarray(values.transpose(0, 2, 1))


def fit_representation(windows, config, seed):
    """호출자가 전달한 학습 Window로만 bias와 변환 피처 스케일을 맞춘다."""
    from aeon.transformations.collection.convolution_based import MiniRocket
    transformer = MiniRocket(n_kernels=config['n_kernels'],
                            max_dilations_per_kernel=config['max_dilations_per_kernel'],
                            n_jobs=config['n_jobs'], random_state=seed)
    representation = transformer.fit_transform(as_channels_first(windows))
    scaler = StandardScaler(with_mean=False, copy=False)
    representation = scaler.fit_transform(representation)
    return transformer, scaler, representation


def fit_classifier(representation, labels, regularization_c, config, seed):
    if set(np.asarray(labels)) != {0, 1}:
        raise ValueError('학습에는 정상/음주 두 클래스가 필요합니다.')
    # 양의 상관된 변환 피처에서 dual 방식의 미수렴을 피한다. 목적함수는 같다.
    classifier = LogisticRegression(C=regularization_c, solver='liblinear', dual=False,
                                    class_weight='balanced', random_state=seed,
                                    max_iter=config['classifier_max_iter'],
                                    tol=config['classifier_tolerance'])
    # 미수렴 결과를 정상 완료한 모델로 저장하지 않는다.
    with warnings.catch_warnings():
        warnings.simplefilter('error', ConvergenceWarning)
        classifier.fit(representation, labels)
    return classifier


@dataclass
class RocketModel:
    transformer: object
    scaler: StandardScaler
    classifier: LogisticRegression

    def predict_scores(self, windows, batch_size=512):
        values = as_channels_first(windows)
        scores = []
        for start in range(0, len(values), batch_size):
            transformed = self.transformer.transform(values[start:start+batch_size])
            transformed = self.scaler.transform(transformed)
            scores.append(self.classifier.predict_proba(transformed)[:, 1])
        return np.concatenate(scores)
