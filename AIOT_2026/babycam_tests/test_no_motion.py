import copy
import tempfile
import unittest
from pathlib import Path

import torch

from normal_pipeline.no_motion import preservation_loss, sha256, validate_records


class NoMotionTests(unittest.TestCase):
    def test_energy_penalty_has_amplitude_information(self):
        x = torch.tensor([[-1., 1.]])
        zero = torch.zeros_like(x)
        a = preservation_loss(zero, zero, x, 1.)
        b = preservation_loss(zero, zero, 10*x, 1.)
        self.assertAlmostEqual(b.item()/a.item(), 100.)

    def test_step_suppresses_static_output_without_updating_teacher(self):
        teacher = torch.tensor([[2., -1.]], requires_grad=True)
        breathing = torch.nn.Parameter(teacher.detach().clone())
        still = torch.nn.Parameter(torch.ones(1, 2))
        opt = torch.optim.SGD([breathing, still], lr=.1)
        before = still.detach().square().mean().item()
        loss = preservation_loss(breathing, teacher, still, 1.)
        loss.backward(); opt.step()
        self.assertIsNone(teacher.grad)
        self.assertTrue(torch.equal(breathing.detach(), teacher.detach()))
        self.assertLess(still.detach().square().mean().item(), before)

    def test_invalid_losses_rejected(self):
        x = torch.ones(1, 2)
        for weight in [-1., 0., float('nan')]:
            with self.assertRaises(ValueError):
                preservation_loss(x, x, x, weight)
        for still in [torch.empty(0), torch.tensor([float('nan')])]:
            with self.assertRaises(ValueError):
                preservation_loss(x, x, still, 1.)
        with self.assertRaises(ValueError):
            preservation_loss(x, torch.ones(2, 1), x, 1.)

    def record(self, subject='AIR_125:S01', split='train'):
        return dict(id=subject, group_id=subject, split=split, kind='breathing_candidate',
                    source='fake.mp4', source_sha256='a'*64, start_sec=0, end_sec=30,
                    review=dict(approved=True, reviewer='tester', notes='Reviewed full interval'))

    def test_pending_and_string_bool_never_train(self):
        for approved in [False, 'False', 'True']:
            row = self.record(); row['review']['approved'] = approved
            with self.assertRaises(ValueError):
                validate_records([row], require_approved=True, verify_files=False)

    def test_full_subject_id_and_leakage(self):
        a = self.record(); b = self.record('AIR_400:S01', 'test')
        b['source_sha256'] = 'b'*64
        validate_records([a, b], require_approved=True, verify_files=False)
        b = copy.deepcopy(a); b.update(id='another', split='test')
        with self.assertRaises(ValueError):
            validate_records([a, b], require_approved=False, verify_files=False)

    def test_review_identity_and_short_video(self):
        row = self.record(); row['review']['reviewer'] = ''
        with self.assertRaises(ValueError):
            validate_records([row], require_approved=True, verify_files=False)
        row = self.record(); row['end_sec'] = 29
        with self.assertRaises(ValueError):
            validate_records([row], require_approved=False, verify_files=False)

    def test_file_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'clip.mp4'; path.write_bytes(b'original fixture')
            row = self.record(); row.update(source=str(path), source_sha256=sha256(path))
            validate_records([row], require_approved=True)
            path.write_bytes(b'replaced fixture')
            with self.assertRaises(ValueError):
                validate_records([row], require_approved=True)

    def test_same_source_cannot_cross_split_with_different_subject_label(self):
        a = self.record(); b = self.record('AIR_400:S01', 'test')
        with self.assertRaises(ValueError):
            validate_records([a, b], require_approved=False, verify_files=False)

    def test_unapproved_records_can_be_audited_without_becoming_approved(self):
        row = self.record(); row['review']['approved'] = False
        result = validate_records([row], require_approved=False, verify_files=False)
        self.assertEqual(result['pending_review'], 1)
        self.assertIs(row['review']['approved'], False)

    def test_existing_experiment_is_not_overwritten(self):
        from prepare_no_motion_experiment import initialize
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            sentinel = directory/'manifest.json'; sentinel.write_text('keep')
            with self.assertRaises(ValueError):
                initialize(directory)
            self.assertEqual(sentinel.read_text(), 'keep')


if __name__ == '__main__':
    unittest.main()
