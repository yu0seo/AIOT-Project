# 확인한 원본과 근거

확인일: 2026-11-18. 기존 로컬 저장소 `C:\Users\OHS\air-400`의 실제 코드와 공개 공식 코드를 대조했습니다. 로컬 소스·모델의 SHA-256은 `verification_real.json`에 기록되어 있습니다.

- [AIR-400 공식 README](https://github.com/michaelwwan/air-400): AIR_125와 AIR_400의 독립 영아 ID, 서로 다른 영상/라벨 경로.
- [공식 데이터 배포 서버](https://coe.northeastern.edu/Research/AClab/AIR-400/), [배포 설명](https://coe.northeastern.edu/Research/AClab/AIR-400/readme.txt): 학습용 번호 영상, 라벨, AIR_125 ZIP의 다운로드 출처.
- [AIR125Dataset](https://github.com/michaelwwan/air-400/blob/main/dataloaders/air125_dataset.py), [AIR400Dataset](https://github.com/michaelwwan/air-400/blob/main/dataloaders/air400_dataset.py): 동일 stem의 mp4/hdf5 대응.
- [BaseDataset](https://github.com/michaelwwan/air-400/blob/main/dataloaders/base_dataset.py): `respiration` 키 사용과 전체 길이를 맞추는 기존 라벨 보간. 실제 다운로드 HDF5에서도 직접 키를 확인했습니다.
- [InferenceDataset](https://github.com/michaelwwan/air-400/blob/main/dataloaders/inference_dataset.py): 프레임 RGB 변환, 전처리 및 NDCHW 변환.
- [infer.py](https://github.com/michaelwwan/air-400/blob/main/infer.py): build_model/run_inference, 배치별 frame-depth 절단, 후처리, HDF5 `time_sec`/`respiration` 출력.
- [PreProcessor](https://github.com/michaelwwan/air-400/blob/main/processors/pre_processor.py): 영상 단위 ROI/flow/표준화와 chunking.
- [PostProcessor](https://github.com/michaelwwan/air-400/blob/main/processors/post_processor.py): diff 출력의 누적합, detrend, 영아 0.3~1.0Hz 필터.
- [SciPy resample_poly](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.resample_poly.html): anti-aliasing FIR을 적용하는 유리수 비율 리샘플링. 이 구현은 `padtype='line'`을 고정하며 학습/서비스 공통 경로에 사용합니다.
- [공식 논문 3.2 Annotation Process](https://arxiv.org/html/2512.06888v1#S3.SS2): 사람이 표시한 호흡 시점을 impulse로 만든 뒤 가우시안 커널과 합성해 정답 주석 파형을 만드는 과정. 센서 연속 호흡량이 아닙니다.
- [MDN의 MP4V-ES 브라우저 지원 설명](https://developer.mozilla.org/en-US/docs/Web/Media/Guides/Formats/Video_codecs#mp4v-es): MPEG-4 Part 2 영상의 Chrome/Edge 지원 문제와 H.264/VP8 등 대안. 실제 Chrome에서 원본 FMP4가 MediaError 4로 실패하고 복사본이 재생됨을 재현·검증했습니다.
- [imageio-ffmpeg 0.6.0의 Windows 배포 파일](https://pypi.org/project/imageio-ffmpeg/0.6.0/): 환경에 설치하지 않고 작업 폴더에 다운로드하여 FFmpeg 실행 파일만 사용했습니다. wheel SHA-256 `02fa47c83703c37df6bfe4896aab339013f62bf02c5ebf2dce6da56af04ffc0a`를 PyPI 제공 값과 비교했습니다.

공식 README의 소개 숫자와 실제 호스팅 파일 수를 동일하다고 가정하지 않았습니다. 이 실행에서는 AIR_400 번호 영상 295개/라벨 275개, AIR_125 로컬 영상 99개/라벨 125개를 확인했습니다. AIR_125 외부 링크 26개 및 라벨 누락 20개는 별도로 보고합니다.
