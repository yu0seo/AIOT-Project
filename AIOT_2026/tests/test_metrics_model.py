"""오탐률 기준 임계값과 학습 가능한 모델의 계약을 검증한다."""
import unittest

import numpy as np
import pandas as pd
import torch

from idd_classifier.metrics import binary_metrics, select_threshold, evaluate_predictions
from idd_classifier.model import DrivingLSTM


class MetricsModelTests(unittest.TestCase):
    def test_confusion_and_fpr(self):
        metrics = binary_metrics([0, 0, 1, 1], [.1, .7, .4, .9], .5)
        self.assertEqual(metrics['confusion_matrix'], [[1, 1], [1, 1]])
        self.assertEqual(metrics['fpr'], .5)
        self.assertEqual(metrics['recall'], .5)
        self.assertIsNone(binary_metrics([0, 0], [.1, .3], .5)['roc_auc'])

    def test_threshold_uses_only_given_validation_and_respects_fpr(self):
        frame = pd.DataFrame({'participant': ['A']*4+['B']*4, 'label': [0, 0, 1, 1]*2,
                              'score': [.1, .4, .6, .8, .2, .3, .7, .9]})
        result = select_threshold(frame, 0)
        metrics = binary_metrics(frame.label, frame.score, result['threshold'])
        self.assertEqual(metrics['fpr'], 0)
        self.assertEqual(metrics['recall'], 1)
        result = evaluate_predictions(frame, result['threshold'], 10, 42)
        self.assertEqual(len(result['per_participant']), 2)
        self.assertEqual(result['participant_condition']['n'], 4)

    def test_lstm_shape_and_parameter_update(self):
        torch.manual_seed(42)
        model = DrivingLSTM(hidden_size=8, num_layers=1, dropout=.2)
        optimizer = torch.optim.AdamW(model.parameters(), lr=.01)
        x = torch.randn(6, 30, 4)
        before = model.classifier.weight.detach().clone()
        logits = model(x)
        self.assertEqual(tuple(logits.shape), (6,))
        loss = torch.nn.BCEWithLogitsLoss()(logits, torch.tensor([0., 1.]*3))
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        self.assertTrue(torch.isfinite(loss))
        self.assertFalse(torch.equal(before, model.classifier.weight.detach()))


if __name__ == '__main__': unittest.main()
