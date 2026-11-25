"""Build/check reviewable input records. Does not preprocess or train models."""
import argparse
import csv
import json
from pathlib import Path

from normal_pipeline.no_motion import ROOT, sha256, validate_records


def initialize(destination):
    # Exclusive directory creation prevents overwriting any earlier review/experiment.
    if destination.exists():
        raise ValueError('새 --output 폴더를 지정하세요. 이전 실험은 덮어쓰지 않습니다.')
    with (ROOT/'output/ae_results_v2/splits.csv').open(encoding='utf-8-sig', newline='') as fp:
        splits = list(csv.DictReader(fp))
    chosen = {}
    for row in splits:
        meta = json.loads(row['metadata_json'])
        if meta['start_sec'] != 0 or meta['subject_id'] in chosen:
            continue
        original = Path(meta['video'])
        source = ROOT.joinpath(*original.parts[original.parts.index('data'):])
        chosen[meta['subject_id']] = dict(
            id=row['video_id']+'_0_30', group_id=meta['subject_id'], split=row['split'],
            kind='breathing_candidate', source=source.relative_to(ROOT).as_posix(),
            source_sha256=meta['source_sha256'], start_sec=0, end_sec=30,
            review=dict(approved=False, reviewer='', notes=''),
            provenance='Existing split preserved; label_status='+meta['label_status'])
    records = list(chosen.values())
    doll = ROOT/'output/doll_retest_88_102_20261125/work/batches/000000000088_000000000102/merged.mp4'
    if doll.is_file():
        records.append(dict(id='static_doll_88_102', group_id='STATIC:doll_session_88_102',
                            split='train', kind='static_real', source=doll.relative_to(ROOT).as_posix(),
                            source_sha256=sha256(doll), start_sec=0, end_sec=30,
                            review=dict(approved=True, reviewer='user confirmation and recorded frame inspection',
                                        notes='User reported no handling from TS88; static doll bench input, not clinical apnea.'),
                            provenance='docs/DOLL_TEST_DIAGNOSIS_20261125.md'))
    counts = validate_records(records, require_approved=False)
    checkpoint = ROOT/'checkpoints/DeepPhys_Deep_Body_best.pth'
    document = dict(schema=1, teacher_checkpoint=checkpoint.relative_to(ROOT).as_posix(),
                    teacher_sha256=sha256(checkpoint), records=records,
                    limitation='Preparation only. No approved breathing data or independent real static holdout yet.')
    destination.mkdir(parents=True, exist_ok=False)
    (destination/'manifest.json').write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 정지 입력 억제 실험: 검토할 구간', '',
             '각 영상의 0~30초를 확인합니다. 호흡 움직임·가림·큰 동작을 검토하고, 불확실하면 승인하지 않습니다.',
             'teacher 목표는 기존 동작 보존용이며 실제 호흡 정답을 대신하지 않습니다.', '',
             '| ID | 기존 split | 종류 | 승인 | 영상 |', '|---|---|---|---|---|']
    for r in records:
        path = (ROOT/r['source']).as_posix()
        lines.append(f'| {r["id"]} | {r["split"]} | {r["kind"]} | {r["review"]["approved"]} | [영상 열기](<{path}>) |')
    lines.extend(['', '검토 후 manifest.json의 해당 review에 approved: true, reviewer, notes를 기록합니다.',
                  'valid/test는 학습에 사용하지 않습니다. 판단이 어려운 항목은 목록에서 제외해도 됩니다.',
                  '모든 정상 후보를 무조건 승인하지 마세요. 학습·검증에 사용할 실제 관찰 가능한 구간만 선택합니다.',
                  '실제 정지 인형은 현재 한 촬영뿐입니다. 별도 정지 촬영과 주기적 흉곽 움직임 대조군이 추가로 필요합니다.'])
    (destination/'REVIEW.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return counts


def check(path, ready):
    document = json.loads(path.read_text(encoding='utf-8-sig'))
    if document.get('schema') != 1:
        raise ValueError('manifest schema 오류')
    if sha256(ROOT/document['teacher_checkpoint']) != document['teacher_sha256']:
        raise ValueError('teacher 가중치 해시가 다릅니다.')
    counts = validate_records(document['records'], require_approved=ready)
    if ready:
        for split, kind in [('train', 'breathing_candidate'), ('valid', 'breathing_candidate'), ('train', 'static_real')]:
            if not counts.get(f'{split}:{kind}'):
                raise ValueError(f'필요한 데이터 없음: {split}:{kind}')
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init'); init.add_argument('--output', type=Path, required=True)
    test = sub.add_parser('check'); test.add_argument('manifest', type=Path)
    test.add_argument('--require-approved', action='store_true')
    cache = sub.add_parser('cache', help='승인된 구간만 생산 전처리로 준비; 학습하지 않음')
    cache.add_argument('manifest', type=Path)
    cache.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'init':
            result = initialize(args.output.resolve())
        elif args.command == 'check':
            result = check(args.manifest, args.require_approved)
        else:
            from normal_pipeline.no_motion_cache import prepare_cache
            result = prepare_cache(args.manifest.resolve(), args.output.resolve())
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f'오류: {exc}\n')


if __name__ == '__main__':
    main()
