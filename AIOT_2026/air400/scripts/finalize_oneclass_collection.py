"""Finalize availability metadata, source coverage and numerical audits after both dataset runs."""
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import time

import h5py
import numpy as np

from air400_paths import DATA, PROJECT
from download_oneclass_sources import save
from extract_oneclass_30s import consolidate, sources
from validate_oneclass_exports import main as validate
from prepare_computable_subset import write_subset

OUT = PROJECT/"06_단일클래스_학습데이터"


def main():
    # A worker publishes finished_sources before its last shared index write.
    # Wait for its terminal marker before correcting or rebuilding shared files.
    for name in ("extraction_status.json", "extraction_status_air-125.json"):
        status_path = OUT/"configs"/name
        for attempt in range(30):
            state = json.loads(status_path.read_text(encoding="utf-8"))
            if "all_exported_segments" in state:
                break
            time.sleep(1)
        else:
            raise RuntimeError(f"Worker has not finalized its index: {name}")
    # Both source versions have the same numerical pipeline. Older in-flight
    # exports need the earliest-availability annotation corrected: zero-phase
    # filtering and standardization observe the whole 30s, not just a prefix.
    for path in sorted((OUT/"hdf5").glob("*/*/*.hdf5")):
        with h5py.File(path, "r+") as f:
            if "features/rolling_reference_end_sec" not in f:
                f.create_dataset("features/rolling_reference_end_sec", data=np.arange(10, 31, dtype=np.float64))
            f["features/rolling_available_at_sec"][:] = 30.
            if "time/available_at_source_time_sec" not in f:
                f.create_dataset("time/available_at_source_time_sec", data=np.full(300, float(f.attrs["segment_end_sec"])))
            assert np.all(f["features/rolling_available_at_sec"][:] == 30.)
    records = consolidate()
    validate()
    subset = write_subset()
    items = sources()
    present = set(r["id"] for r in records)
    expected_segments = 0
    incomplete_windows = []
    for identifier in sorted(present):
        group = [r for r in records if r["id"] == identifier]
        count = int(np.floor((group[0]["source_info"]["last_frame_time_sec"]+.15)/30))
        expected_segments += count
        wanted = list(range(0, count*30, 30))
        actual = sorted(r["segment_start_sec"] for r in group)
        if wanted != actual:
            incomplete_windows.append({"id": identifier, "expected_starts_sec": wanted, "actual_starts_sec": actual})
    hashes = {}
    for r in records: hashes.setdefault(r["source_video_sha256"], set()).add(r["id"])
    duplicate_sets = [sorted(v) for v in hashes.values() if len(v)>1]
    videos = list((DATA/"datasets/AIR_125").glob("S*/*.mp4"))
    annotations = list((DATA/"datasets/AIR_125").glob("S*/*.hdf5"))
    missing_air125 = [str(p.relative_to(DATA)) for p in annotations if not p.with_suffix(".mp4").exists()]
    archive_inventory = json.loads((OUT/"configs/air125_archive_inventory.json").read_text(encoding="utf-8"))
    coverage = {"completed_at": datetime.now().astimezone().isoformat(), "source_videos_available": len(items),
        "source_videos_exported": len(present), "segments": len(records),
        "expected_segments_for_decoded_sources": expected_segments, "incomplete_source_windows": incomplete_windows,
        "dataset_video_count": dict(Counter(r["dataset"] for r in items)),
        "dataset_segment_count": dict(Counter(r["dataset"] for r in records)),
        "sources_without_exports": [r for r in items if r["id"] not in present],
        "exact_duplicate_source_video_sets": duplicate_sets,
        "air125_archive_video_count": archive_inventory["video_count"],
        "air125_total_available_video_count": len(videos),
        "air125_external_prepared_video_count": len(videos)-archive_inventory["video_count"],
        "air125_annotation_files_without_paired_video": missing_air125,
        "normal_labels_assigned": False, "anomaly_model_trained": False,
        "fps": 10, "window_sec": 30, "waveform_shape": [len(records), 300, 1],
        "interval_feature_shape": [len(records), 9], "rolling_interval_feature_shape": [len(records), 21, 9], "face_observations": len(records)*31,
        "availability": "Whole-window normalization and filtfilt outputs become available at the 30s input end", **subset}
    save(OUT/"configs/collection_summary.json", coverage)
    assert not incomplete_windows, incomplete_windows
    report = ["DeepPhys 30초 데이터 추출 결과", "",
              f"실제 사용 가능한 원본 영상: {len(items)}개", f"추출된 원본 영상: {len(present)}개",
              f"30초 HDF5 파일: {len(records)}개", "조건: 10FPS / 30초 / 파형 300개",
              f"파형 배열 크기: ({len(records)}, 300, 1)", f"호흡 간격 요약 특성 배열 크기: ({len(records)}, 9)",
              f"얼굴 실제 검사 결과: {len(records)*31}회", "",
              f"기본 검출/시간 정렬 조건 및 요약 특성 결측 검사 통과 후보: {subset['computable_summary_candidates']}개",
              f"그 외 검토 표시 구간: {subset['other_candidates_flagged']}개",
              "수치 완전성 기준으로 묶은 파일: model_input_candidates_computable.npz",
              "이 묶음도 정상 호흡으로 확인한 데이터라는 뜻은 아닙니다.", "",
              "데이터셋별 30초 파일: "+json.dumps(coverage["dataset_segment_count"], ensure_ascii=False),
              f"AIR-125에서 짝이 되는 영상이 없는 주석 파일: {len(missing_air125)}개",
              f"추출 결과가 없는 확보 영상: {len(coverage['sources_without_exports'])}개", "",
              "HDF5: hdf5/ 아래 데이터셋/대상 폴더", "전체 배열: model_input_candidates.npz",
              "파일 목록·원본·구간·품질: index.json", "필드 설명과 읽기 예: 데이터설명.txt", "",
              "정상 라벨은 자동 부여하지 않았으며 이상 탐지 모델을 학습한 결과가 아닙니다.",
              "추정 호흡점은 모델 파형에서 찾은 지점이며 실제 호흡 시점 주석과 구분합니다."]
    (OUT/"추출결과.txt").write_text("\n".join(report)+"\n", encoding="utf-8")
    print(json.dumps({k:v for k,v in coverage.items() if k!="air125_annotation_files_without_paired_video"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
