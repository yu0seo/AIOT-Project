"""Download the official AIR paired-clip release; TLS remains verified."""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import ssl
import time
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import Request, urlopen
import zipfile
import zlib

BASE = 'https://coe.northeastern.edu/Research/AClab/AIR-400/'


def context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.links.extend(v for k, v in attrs if k == 'href' and v)


def list_files(url, suffix):
    with urlopen(url, context=context(), timeout=60) as r:
        parser = Links()
        parser.feed(r.read().decode('utf-8'))
    return sorted({unquote(x) for x in parser.links
                   if re.fullmatch(r'\d+' + re.escape(suffix), unquote(x), re.IGNORECASE)},
                  key=lambda x: int(x.split('.')[0]))


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def download(url, dest):
    """Keep partial files; resume only when server confirms the byte range."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urlopen(Request(url, method='HEAD'), context=context(), timeout=60) as r:
        size = int(r.headers['Content-Length'])
    if dest.exists():
        if dest.stat().st_size == size:
            return {'url': url, 'path': str(dest.resolve()), 'bytes': size, 'sha256': sha256(dest)}
        raise ValueError(f'Existing file size differs; preserve and inspect: {dest}')
    partial = dest.with_suffix(dest.suffix + '.part')
    for attempt in range(4):
        try:
            start = partial.stat().st_size if partial.exists() else 0
            headers = {'Range': f'bytes={start}-'} if start else {}
            with urlopen(Request(url, headers=headers), context=context(), timeout=120) as r:
                resumed = start and r.status == 206 and r.headers.get('Content-Range', '').startswith(f'bytes {start}-')
                with partial.open('ab' if resumed else 'wb') as out:
                    shutil.copyfileobj(r, out, length=1024 * 1024)
            if partial.stat().st_size != size:
                raise IOError(f'Incomplete download: {partial}')
            partial.replace(dest)
            return {'url': url, 'path': str(dest.resolve()), 'bytes': size, 'sha256': sha256(dest)}
        except Exception:
            if attempt == 3:
                raise
            time.sleep(1 + attempt)


def safe_extract(archive, dest):
    dest = Path(dest).resolve()
    with zipfile.ZipFile(archive) as z:
        for member in z.infolist():
            if member.filename.startswith('__MACOSX/') or Path(member.filename).name == '.DS_Store':
                continue
            target = (dest / member.filename).resolve()
            if not target.is_relative_to(dest) or '\\' in member.filename or (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError(f'Unsafe archive member: {member.filename}')
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if target.exists():
                crc = 0
                with target.open('rb') as existing:
                    for block in iter(lambda: existing.read(1024 * 1024), b''):
                        crc = zlib.crc32(block, crc)
                if target.stat().st_size != member.file_size or crc != member.CRC:
                    raise ValueError(f'Existing extracted file differs: {target}')
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(member) as source, target.open('wb') as out:
                shutil.copyfileobj(source, out)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dest', type=Path, default=Path('data'))
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--skip-air125', action='store_true')
    args = ap.parse_args()
    dest = args.dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    jobs, unpaired = [], []
    for i in range(1, 11):
        subject = f'S{i:02d}'
        url = urljoin(BASE, subject + '/')
        videos = list_files(url, '.mp4')
        labels = list_files(url + 'out/', '.hdf5')
        if not videos or not labels:
            raise ValueError(f'Empty official subject listing: {subject}')
        missing = {Path(x).stem for x in videos} - {Path(x).stem for x in labels}
        if missing:
            unpaired.append({'subject': subject, 'videos_without_labels': sorted(missing, key=int)})
            print(f'Official release: {subject} has {len(missing)} videos without matching labels; will download and exclude from scan.', flush=True)
        jobs.extend((urljoin(url, x), dest / 'AIR_400' / subject / x) for x in videos)
        jobs.extend((urljoin(url + 'out/', x), dest / 'AIR_400' / subject / 'out' / x) for x in labels)
    if not args.skip_air125:
        jobs.append((urljoin(BASE, 'AIR_125.zip'), dest / 'archives' / 'AIR_125.zip'))
    print(f'Downloading/verifying {len(jobs)} official files into {dest}', flush=True)
    records, errors = [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(args.workers, 8))) as pool:
        futures = {pool.submit(download, url, path): url for url, path in jobs}
        for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
            try:
                record = future.result()
                records.append(record)
            except Exception as e:
                errors.append({'url': futures[future], 'error': str(e)})
            if i % 25 == 0 or i == len(jobs):
                print(f'{i}/{len(jobs)} done; errors={len(errors)}', flush=True)
    report = {'base': BASE, 'files': sorted(records, key=lambda x: x['path']), 'errors': errors, 'unpaired': unpaired,
              'scope': 'All published AIR_400 numbered clips and out/*.hdf5 plus AIR_125.zip. Supplemental originals/visualizations are excluded.'}
    (dest / 'download_report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    if errors:
        raise RuntimeError(f'{len(errors)} downloads failed; see download_report.json; rerun to resume')
    if not args.skip_air125:
        safe_extract(dest / 'archives' / 'AIR_125.zip', dest)
        print('AIR_125 archive extracted. S06-S08 may contain web links rather than local MP4s.', flush=True)
    print('Download and size/hash verification complete.', flush=True)


if __name__ == '__main__':
    main()
