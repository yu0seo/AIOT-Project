"""Refresh the folder guide and organize existing artifacts; no training/inference."""
from datetime import datetime
import hashlib
import html
import json
import shutil

from air400_paths import AFTER, ARCHIVE, BEFORE, DATA, FINETUNE, PRESENTATION, PROJECT, PYTHON, RUNTIME


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def checksum(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def copy_verified(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and checksum(source) != checksum(target):
        raise RuntimeError(f"Refusing to replace a different artifact: {target}")
    if not target.exists():
        shutil.copy2(source, target)
    return {"source": source.relative_to(PROJECT).as_posix(),
            "copy": target.relative_to(PROJECT).as_posix(), "sha256": checksum(target)}


def main():
    video_count = len(list((DATA / "videos").glob("*/*.mp4")))
    comparison_path = PROJECT / "comparison_status.json"
    comparison = json.loads(comparison_path.read_text(encoding="utf-8")) if comparison_path.exists() else {}
    finished = comparison.get("status") == "completed_exploratory"
    for root in (BEFORE, AFTER):
        for name in ("models", "waveforms", "bounding_boxes", "waveform_plots", "metrics", "configs"):
            (root / name).mkdir(parents=True, exist_ok=True)
    for split in ("train", "val", "test"):
        for kind in ("images", "labels"):
            (FINETUNE / "dataset" / kind / split).mkdir(parents=True, exist_ok=True)
    for name in ("labeling_samples", "runs", "models", "configs"):
        (FINETUNE / name).mkdir(parents=True, exist_ok=True)
    (DATA / "splits").mkdir(exist_ok=True)
    pt = ["01_좌우비교영상", "02_전후파형그래프", "03_전체시험성능", "04_개선실패사례",
          "05_실험개요", "06_라벨링데이터샘플", "90_기존실험참고"]
    for name in pt:
        (PRESENTATION / name).mkdir(parents=True, exist_ok=True)
    notes = {
        DATA: f"공통 원본: videos=다운로드 영상, references=공개 호흡 주석, source=공개 소스, weights=공개 가중치.\n현재 영상 {video_count}개 확보. 전체 295개 확보 완료를 뜻하지 않습니다.\nreferences HDF5는 DeepPhys 예측이 아닙니다. assets.json과 Chest configs/download_checksums.json에 출처·SHA256을 보존합니다.\n",
        BEFORE: "파인튜닝 전 모델·파형·박스 화면·설정·지표입니다.\nS01_1_pilot은 이전 예비 결과입니다. control_v1 하위 폴더가 이번 동일 조건 비교 결과입니다.\n전체 진행 상태와 생성 개수는 project_status.json에서 확인하세요.\n",
        FINETUNE: "Chest 파인튜닝 자료. dataset/images와 labels에 같은 이름의 이미지·라벨을 저장합니다.\n촬영 원본/대상 그룹으로 train/val/test를 분리합니다.\n기존 수동 ROI는 검수된 학습 정답이 아닙니다. 현재 상태는 project_status.json을 확인하세요.\nlabeling_samples에는 실제 라벨 검수 후 이미지+정답 박스 샘플을 저장합니다.\n",
        AFTER: "파인튜닝 후 결과 저장 위치. 현재 상태는 project_status.json을 확인하세요.\n전 단계와 같은 models/waveforms/bounding_boxes/waveform_plots/metrics/configs 구조로 저장합니다.\n",
        PRESENTATION: "01=전후 좌우 영상, 02=기준 주석/전/후 파형, 03=시험 전체 지표,\n04=개선·실패 사례, 05=분리/학습/비교 조건, 06=실제 학습 라벨 샘플.\n90은 기존 4모델 비교이며 전후 개선 증거가 아닙니다. 현재 상태는 project_status.json을 확인하세요.\n",
        ARCHIVE: "기존 실험 보존. results=공식 자동 Chest S01 파일럿,\nresults_manual_chest=수동 상체 10영상 4모델 비교와 중복 프레임 30fps 대조,\nreport=기존 보고서, logs=실행 기록. 수동 ROI를 YOLO 파인튜닝 후 결과로 사용하지 마세요.\n",
    }
    for folder, note in notes.items():
        (folder / "안내.txt").write_text(note, encoding="utf-8")
    for name in pt[:-1]:
        (PRESENTATION / name / "상태.txt").write_text(
            "자료 생성 완료. 05_실험개요/index.html에서 결과와 범위를 확인하세요.\n" if finished else
            "자료 저장 위치입니다. 실제 학습·라벨 검수·전후 비교 결과가 없으면 준비 중입니다.\n현재 상태는 프로젝트 최상단 project_status.json에서 확인하세요.\n", encoding="utf-8")
    copies = []
    for name in ("DeepPhys_Deep_Body_best.pth", "yolov8m.pt", "yolov8n-face.pt"):
        copies.append(copy_verified(DATA / "weights" / name, BEFORE / "models" / name))
    pilot = ARCHIVE / "results" / "S01_1_native"
    for source, target in [("DeepPhys_pred.hdf5", "waveforms/S01_1_pilot_pred.hdf5"),
                           ("roi.jpg", "bounding_boxes/S01_1_pilot_roi.jpg"),
                           ("summary.json", "metrics/S01_1_pilot_summary.json")]:
        copies.append(copy_verified(pilot / source, BEFORE / target))
    config = json.loads((ARCHIVE / "results" / "model_details.json").read_text(encoding="utf-8"))["DeepPhys"]
    write_json(BEFORE / "configs" / "pilot_deepphys.json", config)
    write_json(BEFORE / "artifact_manifest.json", {"status": "controlled_comparison_complete_plus_older_pilot" if finished else "pilot_copies_and_study_in_progress", "copies": copies,
                "controlled_waveforms": "waveforms/control_v1", "pilot_not_paired_baseline": True})
    plot_path = BEFORE / "waveform_plots" / "S01_1_pilot_waveform.png"
    if not plot_path.exists():
        import os
        os.environ["MPLCONFIGDIR"] = str(RUNTIME / "matplotlib")
        import h5py
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        with h5py.File(BEFORE / "waveforms" / "S01_1_pilot_pred.hdf5", "r") as handle:
            times, wave = handle["time_sec"][:], handle["respiration"][:]
        fig, ax = plt.subplots(figsize=(11, 3.5), layout="constrained")
        ax.plot(times, wave, color="#1874d1", linewidth=1.2)
        ax.set(title="S01/1 - DeepPhys + official automatic Chest (pilot, before fine-tuning)",
               xlabel="Video time (seconds)", ylabel="Predicted respiration (model units)")
        ax.grid(alpha=.2)
        fig.savefig(plot_path, dpi=150)
        plt.close(fig)
    for name in ("manual_chest_comparison.png", "automatic_roi_audit.jpg"):
        copy_verified(ARCHIVE / "report" / name, PRESENTATION / "90_기존실험참고" / name)
    (PRESENTATION / "90_기존실험참고" / "주의.txt").write_text(
        "기존 4모델·수동 ROI 비교입니다. 파인튜닝 전후 비교가 아닙니다.\n주황색 박스는 실험용 수동 ROI이며 실제 학습 라벨이 아닙니다.\n", encoding="utf-8")
    report = ARCHIVE / "report" / "index.html"
    report.write_text(report.read_text(encoding="utf-8").replace('href="../assets.json"',
                      'href="../../00_공통자료/assets.json"'), encoding="utf-8")
    label_count = len(list((FINETUNE / "dataset" / "labels").rglob("*.txt")))
    trained_models = list((FINETUNE / "models").glob("*.pt")) + list((FINETUNE / "runs").rglob("best.pt"))
    after_count = len(list((AFTER / "waveforms").rglob("*.hdf5")))
    before_count = len(list((BEFORE / "waveforms").rglob("*.hdf5")))
    status = {"updated_at": datetime.now().astimezone().isoformat(),
              "downloaded_videos": len(list((DATA / "videos").glob("*/*.mp4"))),
              "before": {"status": "pilot_only" if before_count == 1 else "outputs_present", "waveform_files": before_count},
              "finetuning": {"status": "model_present" if trained_models else ("labels_present" if label_count else "not_started"), "label_files": label_count},
              "after": {"status": "outputs_present" if after_count else "not_started", "waveform_files": after_count},
              "paired_before_after_presentation": "completed_exploratory" if finished else ("requires_verification" if after_count else "pending"), "runtime_python": str(PYTHON)}
    write_json(PROJECT / "project_status.json", status)
    cards = [(DATA, f"영상·호흡 주석·소스·공개 가중치 / 영상 {video_count}개 확보"),
             (BEFORE, f"모델·예측 파형·박스·설정·지표 / 파형 {before_count}개 (기존 파일럿 포함)"),
             (FINETUNE, f"이미지·정답 라벨·라벨 샘플·학습 기록 / 라벨 {label_count}개"),
             (AFTER, f"전 단계와 같은 결과 구조 / 파형 {after_count}개"),
             (PRESENTATION, "전후 영상·파형·지표·사례·실험 개요·라벨 샘플 / "+("완료·범위 제한 있음" if finished else "준비 중")),
             (ARCHIVE, "지난 4모델 비교 보고서와 원본 결과 보존"),
             (PROJECT / "scripts", "실행 코드·공통 경로 설정")]
    sections = []
    for folder, description in cards:
        files = sorted(p for p in folder.rglob("*") if p.is_file() and "__pycache__" not in p.parts
                       and p.suffix in {".txt", ".html", ".json", ".png", ".jpg", ".hdf5", ".pt", ".pth", ".py"})
        shown = files if folder in (BEFORE, PRESENTATION, PROJECT / "scripts") else files[:5]
        links = ''.join(f'<li><a href="{html.escape(p.relative_to(PROJECT).as_posix(), quote=True)}">{html.escape(p.relative_to(folder).as_posix())}</a></li>' for p in shown)
        sections.append(f'<section><h2>{folder.name}</h2><p>{description}</p><details><summary>파일 목록 열기</summary><ul>{links}</ul></details></section>')
    page = '''<!doctype html><html lang="ko"><meta charset="utf-8"><title>AIR-400 프로젝트 자료</title>
<style>body{font:16px/1.6 system-ui,sans-serif;color:#1c2d42;max-width:1080px;margin:38px auto;padding:0 22px;background:#f6f8fb}section{background:white;padding:20px;margin:16px 0;border:1px solid #dce2eb;border-radius:12px}h2{font-size:21px;margin:0}a{color:#1763aa;overflow-wrap:anywhere}.notice{background:#fff0ce;padding:16px;border-radius:8px}li{margin:5px 0}</style>
<h1>AIR-400 프로젝트 자료 안내</h1><p>공통 자료 → 파인튜닝 전 → 학습 → 파인튜닝 후 → PT 자료 순서로 확인합니다.</p>
<p class="notice">Chest 파인튜닝은 시작하지 않았습니다. 파인튜닝 후 결과·실제 학습 라벨 샘플·전후 개선 자료는 아직 없습니다. 기존 수동 ROI 결과를 파인튜닝 후 결과로 표시하지 않습니다.</p>
<p><a href="05_기존모델비교실험/report/index.html">기존 4모델 비교 보고서</a> · <a href="project_status.json">현재 상태</a> · <a href="cleanup_manifest.json">이전 프로젝트 정리 기록</a></p>
'''+''.join(sections)+"</html>"
    if label_count or trained_models or after_count:
        page = page.replace("Chest 파인튜닝은 시작하지 않았습니다. 파인튜닝 후 결과·실제 학습 라벨 샘플·전후 개선 자료는 아직 없습니다.",
                            "새 라벨 또는 모델·파형 파일을 확인했습니다. 현재 상태 JSON과 실제 결과를 확인하세요.")
        page = page.replace("/ 미시작", "/ 현재 상태 JSON 확인").replace("/ 준비 중", "/ 현재 상태 JSON 확인")
    if finished:
        report_link = html.escape(comparison["report"], quote=True)
        result_link = f'<section><h2>이번 Chest 파인튜닝 전후 검증 결과</h2><p><a href="{report_link}">결과 보고서 · 전후 영상·파형·지표·라벨 샘플 열기</a></p><p>{html.escape(comparison["conclusion"]["roi"])} {html.escape(comparison["conclusion"]["waveform"])}</p></section>'
        page = page.replace("<h1>AIR-400 프로젝트 자료 안내</h1>","<h1>AIR-400 프로젝트 자료 안내</h1>"+result_link)
        page = page.replace("새 라벨 또는 모델·파형 파일을 확인했습니다. 현재 상태 JSON과 실제 결과를 확인하세요.",
                            "Chest 학습과 통제 비교를 완료했습니다. 시험 집합이 작고 참조 박스에 독립적인 전문가 검수는 없으므로 보고서의 범위를 확인하세요.")
    goal_status_path=PROJECT/"goal_comparison_status.json"
    if goal_status_path.exists():
        goal_comparison=json.loads(goal_status_path.read_text(encoding="utf-8"))
        if goal_comparison.get("status")=="completed_exploratory":
            link=html.escape(goal_comparison["report"],quote=True)
            panel=f'<section><h2>Body·Chest · 호흡 시점과 움직임 보존 비교</h2><p><a href="{link}">공식 순서 / 기존 전처리 / 정지·감소 대조 결과 열기</a></p><p>{html.escape(goal_comparison["timing_conclusion"])} 실제 무호흡 검증은 포함하지 않습니다.</p></section>'
            page=page.replace("<h1>AIR-400 프로젝트 자료 안내</h1>","<h1>AIR-400 프로젝트 자료 안내</h1>"+panel)
    (PROJECT / "index.html").write_text(page, encoding="utf-8")
    print(json.dumps(status, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
