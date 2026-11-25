import json
from pathlib import Path
import tempfile
import unittest

from normal_pipeline.no_motion import sha256
from prepare_respiration_ae import load_source_plan


class SourcePlanTests(unittest.TestCase):
    def test_source_plan_preserves_labels_and_splits_and_rejects_changed_video(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); source=root/'video.mp4'; source.write_bytes(b'source')
            row=dict(id='fixture',group_id='AIR_125:S05',split='train',label='normal_assumed',
                     reviewed=False,source=str(source),source_sha256=sha256(source),start_sec=0,end_sec=30,
                     status='prepared',file='old.npz',file_sha256='unused')
            document=dict(schema=1,complete=True,normal_assumption_authorized=True,records=[row])
            path=root/'dataset.json';path.write_text(json.dumps(document))
            records=load_source_plan(path)
            self.assertEqual(records[0]['split'],'train')
            self.assertFalse(records[0]['reviewed'])
            self.assertNotIn('file',records[0])
            source.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'해시'):
                load_source_plan(path)


if __name__=='__main__':
    unittest.main()
