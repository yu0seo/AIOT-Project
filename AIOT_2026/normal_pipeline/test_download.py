import tempfile
import unittest
from pathlib import Path
import zipfile

from download_data import safe_extract


class DownloadTests(unittest.TestCase):
    def test_zip_cannot_write_outside_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root/'bad.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('../outside.txt', 'untrusted')
            with self.assertRaises(ValueError):
                safe_extract(archive, root/'data')
            self.assertFalse((root/'outside.txt').exists())

    def test_existing_extracted_data_is_not_silently_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root/'data.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('AIR_125/S01/001.hdf5', b'good')
                z.writestr('__MACOSX/metadata', b'ignored')
            dest = root/'data'
            safe_extract(archive, dest)
            self.assertFalse((dest/'__MACOSX').exists())
            safe_extract(archive, dest)
            (dest/'AIR_125/S01/001.hdf5').write_bytes(b'evil')
            with self.assertRaises(ValueError):
                safe_extract(archive, dest)


if __name__ == '__main__':
    unittest.main()
