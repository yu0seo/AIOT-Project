"""개선 후보도 네 피처와 기존 모델 호환성, 참가자 분리를 보존해야 한다."""
import unittest

import numpy as np
import torch

from idd_classifier.data import normalize, transform_features
from idd_classifier.model import DrivingLSTM, create_model
from idd_classifier.tuning import participant_folds, validate_search_config


class ImprovementTests(unittest.TestCase):
    def test_original_lstm_state_dict_remains_compatible(self):
        model = DrivingLSTM(8, 1, 0).eval()
        rebuilt = create_model('LSTM', {'hidden_size': 8, 'num_layers': 1, 'dropout': 0})
        rebuilt.load_state_dict(model.state_dict())
        rebuilt.eval()
        x = torch.randn(2, 30, 4)
        torch.testing.assert_close(model(x), rebuilt(x))

    def test_all_models_accept_exactly_four_features_and_have_gradients(self):
        torch.set_num_threads(2)
        for kind in ['LSTM', 'GRU', 'TCN']:
            model = create_model(kind, {'hidden_size': 8, 'num_layers': 2,
                                        'dropout': .1, 'pooling': 'statistics'})
            for steps in [30, 50, 100]:
                output = model(torch.randn(3, steps, 4))
                self.assertEqual(tuple(output.shape), (3,))
                output.sum().backward()
                self.assertTrue(all(p.grad is not None for p in model.parameters()))
                model.zero_grad()
            with self.assertRaises(ValueError): model(torch.randn(2, 30, 5))

    def test_log_normalization_preserves_sign_and_has_no_clipping(self):
        x = np.array([[-100, -1, 0, 100]], dtype=np.float32)
        transformed = transform_features(x, 'signed_log1p')
        np.testing.assert_array_equal(np.sign(transformed), np.sign(x))
        self.assertGreater(transformed[0, 3], np.log1p(99))
        normalizer = {'mean': [0]*4, 'std': [1]*4, 'transform': 'signed_log1p'}
        np.testing.assert_array_equal(normalize(x, normalizer), transformed)
        np.testing.assert_array_equal(normalize(x, {'mean': [0]*4, 'std': [1]*4}), x)
        with self.assertRaises(ValueError): transform_features(x, 'unknown')

    def test_participant_folds_are_disjoint_and_exhaustive(self):
        participants = [f'P{i}' for i in range(12)]
        folds = participant_folds(participants, 3, 42)
        seen = []
        for fold in folds:
            self.assertFalse(set(fold['train']) & set(fold['validation']))
            self.assertEqual(set(fold['train']) | set(fold['validation']), set(participants))
            seen.extend(fold['validation'])
        self.assertEqual(sorted(seen), sorted(participants))
        self.assertEqual(folds, participant_folds(participants, 3, 42))

    def test_tcn_encoder_does_not_read_future_samples(self):
        model = create_model('TCN', {'hidden_size': 8, 'num_layers': 3, 'dropout': 0}).eval()
        prefix = torch.randn(2, 4, 30)
        extended = torch.cat([prefix, torch.randn(2, 4, 20)*100], dim=2)
        torch.testing.assert_close(model.encoder(prefix), model.encoder(extended)[:, :, :30])

    def test_duplicate_participants_and_unsafe_candidate_names_rejected(self):
        with self.assertRaises(ValueError): participant_folds(['P1']*12, 3, 42)
        base = {'feature': {'sample_hz': 10}}
        search = {'folds': 3, 'epochs': 1, 'patience': 1, 'stride_seconds': 3,
                  'checkpoint_metric': 'macro_auc', 'candidates': [{'name': '../outside'}]}
        with self.assertRaises(ValueError): validate_search_config(base, search)

    def test_comparison_warmup_cannot_be_shorter_than_smoother(self):
        base = {'feature': {'sample_hz': 10}, 'seed': 42}
        search = {'folds': 3, 'epochs': 1, 'patience': 1, 'stride_seconds': 3,
                  'checkpoint_metric': 'macro_auc', 'comparison_warmup_points': 6,
                  'candidates': [{'name': 'small', 'model_type': 'LSTM', 'hidden_size': 8,
                                  'num_layers': 1, 'pooling': 'statistics', 'dropout': .1,
                                  'weight_decay': .001, 'transform': 'identity', 'smooth_points': 7}]}
        with self.assertRaises(ValueError): validate_search_config(base, search)

    def test_larger_lstm_models_backpropagate_through_every_layer(self):
        torch.set_num_threads(2)
        previous = 4993
        for hidden, layers in [(64, 2), (128, 2), (256, 3)]:
            model = DrivingLSTM(hidden, layers, .1, 'statistics')
            parameters = sum(p.numel() for p in model.parameters())
            self.assertGreater(parameters, previous)
            previous = parameters
            logits = model(torch.randn(2, 30, 4))
            self.assertEqual(tuple(logits.shape), (2,))
            logits.square().sum().backward()
            for layer in range(layers):
                gradient = getattr(model.lstm, f'weight_ih_l{layer}').grad
                self.assertIsNotNone(gradient)
                self.assertGreater(float(gradient.norm()), 0)


if __name__ == '__main__': unittest.main()
