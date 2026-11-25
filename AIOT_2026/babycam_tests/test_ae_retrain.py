import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import torch

from normal_pipeline.no_motion import sha256
from retrain_ae_evaluated import run


class AeRetrainTests(unittest.TestCase):
    def build(self,folder,test_amplitude):
        folder.mkdir();records=[]
        roles=[('train',False),('train',False),('valid',False),('valid',True),('test',False),('test',True)]
        for i,(split,negative) in enumerate(roles):
            source=folder/f'fixture_{i}.bin';source.write_bytes(str(i).encode())
            row=dict(id=f'fixture_{i}',group_id=f'fixture:S{i}',split=split,
                     label='static_simulation' if negative else 'normal_assumed',reviewed=negative,
                     source=str(source),source_sha256=sha256(source),status='prepared')
            amplitude=test_amplitude if split=='test' else 1.
            x=(amplitude*np.sin(np.arange(300)*(.3+i*.01))).astype(np.float32)
            file=folder/f'{i}.npz'
            np.savez(file,x_10hz=x,pred_rr_bpm=25.+i,metadata_json=json.dumps(row))
            records.append(dict(row,file=file.name,file_sha256=sha256(file)))
        (folder/'dataset.json').write_text(json.dumps(dict(schema=1,complete=True,records=records,
                 normal_assumption_authorized=True,pipeline_hashes={},
                 active_feature_contract=dict(body_detector_sha256='f'*64,detector_color_corrected=True),
                 limitation='synthetic unit fixture only')))

    def test_changing_only_test_inputs_cannot_select_weights_or_threshold(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for i,amplitude in enumerate([1.,1.2]):
                dataset=root/f'data{i}';self.build(dataset,amplitude)
                args=SimpleNamespace(dataset=dataset,output=root/f'run{i}',epochs=2,patience=2,max_fpr=.05)
                with patch('torch.cuda.is_available',return_value=False),contextlib.redirect_stdout(io.StringIO()):
                    run(args)
            a=torch.load(root/'run0/air400_ae.pt',weights_only=True)
            b=torch.load(root/'run1/air400_ae.pt',weights_only=True)
            self.assertEqual(a['threshold'],b['threshold'])
            self.assertEqual(a['best_epoch'],b['best_epoch'])
            self.assertEqual(a['stats'],b['stats'])
            self.assertEqual(a['feature_contract']['body_detector_sha256'],'f'*64)
            self.assertIs(a['feature_contract']['detector_color_corrected'],True)
            for key in a['state_dict']:
                self.assertTrue(torch.equal(a['state_dict'][key],b['state_dict'][key]),key)


if __name__=='__main__':
    unittest.main()
