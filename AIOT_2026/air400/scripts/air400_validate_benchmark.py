"""Check packing against upstream and the frozen-frame flow shortcut."""
from __future__ import annotations

import json
import logging
import sys

import cv2
import numpy as np
import torch
import yaml

import air400_benchmark as benchmark
import air400_flow_bridge as bridge
from air400_analyze_benchmark import detrend
from air400_paths import ARCHIVE


class SerialPool:
    """Run upstream's pair assembler serially for this eight-frame check."""
    def __init__(self, processes=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def imap(self, function, inputs, chunksize=1):
        return map(function, inputs)


def main():
    benchmark.np, benchmark.cv2, benchmark.torch = np, cv2, torch
    benchmark.flow_bridge = bridge
    sys.modules["pyflow"] = bridge
    module = benchmark.load_module("validation_upstream", benchmark.SOURCE / "processors" / "pre_processor.py")
    module.tqdm = lambda items, **kwargs: items
    module.Pool = SerialPool
    config = yaml.safe_load((benchmark.SOURCE / "configs" / "inference" / "tscan_pca_infer.yaml").read_text())
    config = config["TEST"]["DATA"]["PREPROCESS"]
    config.update(DO_CROP_INFANT_REGION=False, DO_DOWNSAMPLE_BEFORE_PREPROCESS=False)
    processor = module.PreProcessor(config, "", "")
    images, _ = benchmark.read_video(benchmark.DATA / "videos" / "S01" / "1.mp4")
    images = processor.crop_infant_boxes(images[:180], benchmark.MANUAL_CHEST["S01"])
    images, _ = processor._resize_frames(images, [96, 96])
    cv2.setNumThreads(4)
    torch.set_num_threads(4)
    output = {"feature_packing": {}, "freeze_shortcut": {}, "sparse_detrend": {}}
    # Inject the same already-computed flow into upstream's complete preprocess.
    flow = processor.run_optical_flow(images)
    packed, _ = benchmark.pack_features(processor, images, flow)
    run_original_flow = processor.run_optical_flow
    processor.run_optical_flow = lambda unused: flow.copy()
    official, _ = processor.preprocess(images.copy(), np.linspace(0, 1, 180), 10)
    official = official.reshape(-1, 96, 96, 6).transpose(0, 3, 1, 2)
    delta = float(np.max(np.abs(packed - official)))
    output["feature_packing"] = {"max_abs_difference": delta, "shape": list(packed.shape), "passed": delta < 1e-6}
    assert delta < 1e-6, output
    processor.run_optical_flow = run_original_flow
    for method in ("deep", "pca", "coarse2fine"):
        processor.of_method = method
        # Serial upstream path, independent of benchmark's process-pool assembly.
        baseline = processor.run_optical_flow(images[:8])
        frozen, shortcut = benchmark.freeze_flow(processor, images[:8], baseline, method, 2, 6)
        recalculated = processor.run_optical_flow(frozen)
        difference = float(np.max(np.abs(shortcut - recalculated)))
        output["freeze_shortcut"][method] = {"max_abs_difference": difference, "passed": difference < 1e-4}
        assert difference < 1e-4, output
    pp = benchmark.load_module("validation_postprocessor", benchmark.SOURCE / "processors" / "post_processor.py")
    y = np.random.default_rng(1).normal(size=540)
    difference = float(np.max(np.abs(detrend(y) - pp.PostProcessor._detrend_signal(y, 100))))
    output["sparse_detrend"] = {"max_abs_difference": difference, "passed": difference < 1e-8}
    assert difference < 1e-8, output
    output["native_binding"] = bridge.smoke_test()
    benchmark.write_json(ARCHIVE / "report" / "validation.json", output)
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR)
    main()
