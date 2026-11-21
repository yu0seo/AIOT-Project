"""Windows ctypes binding to the original pathak22/pyflow C++ implementation.

The C++ optical-flow algorithm and its parameters are unchanged. This replaces
only Cython's ABI binding, so a global Visual Studio installation is unnecessary.
"""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

from air400_paths import DATA, RUNTIME

LIBRARY = RUNTIME / "coarse2fine.dll"
_dll = None


def build() -> None:
    src = DATA / "source" / "pyflow" / "src"
    runtime = LIBRARY.parent
    runtime.mkdir(parents=True, exist_ok=True)
    wrapper = runtime / "coarse2fine_c_api.cpp"
    wrapper.write_text('''#include "Coarse2FineFlowWrapper.h"
#include "OpticalFlow.h"
extern "C" __declspec(dllexport) int air400_flow(
    double *u, double *v, double *warp, const double *a, const double *b,
    double alpha, double ratio, int minimum, int outer, int inner, int sor,
    int color, int h, int w, int c) {
  try {
    OpticalFlow::IsDisplay = false;
    Coarse2FineFlowWrapper(u, v, warp, a, b, alpha, ratio, minimum,
                          outer, inner, sor, color, h, w, c);
    return 0;
  } catch (...) { return 1; }
}
''', encoding="utf-8")
    env = os.environ.copy()
    env["ZIG_GLOBAL_CACHE_DIR"] = str(runtime / "zig-global-cache")
    env["ZIG_LOCAL_CACHE_DIR"] = str(runtime / "zig-local-cache")
    temporary = runtime / "compiler-temp"
    temporary.mkdir(exist_ok=True)
    env["TEMP"] = str(temporary)
    env["TMP"] = str(temporary)
    compatibility = runtime / "mingw_compat.h"
    compatibility.write_text("#include <cstdlib>\n#include <cstdio>\n#include <vector>\n"
                             "#undef __min\n#undef __max\n", encoding="utf-8")
    command = [sys.executable, "-m", "ziglang", "c++", "-target", "x86_64-windows-gnu",
               "-shared", "-O3", "-std=c++11", "-Wno-deprecated-declarations",
               "-include", str(compatibility),
               "-I", str(src), str(wrapper),
               *[str(x) for x in sorted(src.glob("*.cpp"))], "-o", str(LIBRARY)]
    started = time.perf_counter()
    result = subprocess.run(command, env=env, capture_output=True, text=True)
    (runtime / "compiler.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"Coarse2Fine build failed; see {runtime / 'compiler.log'}\n{result.stderr[-5000:]}")
    (runtime / "compiler.json").write_text(json.dumps(
        {"command": command, "elapsed_sec": time.perf_counter() - started,
         "binding_only": True, "algorithm_source_modified": False}, indent=2), encoding="utf-8")


def coarse2fine_flow(Im1, Im2, alpha=1, ratio=0.5, minWidth=40,
                     nOuterFPIterations=3, nInnerFPIterations=1,
                     nSORIterations=20, colType=0):
    global _dll
    if _dll is None:
        if not LIBRARY.is_file():
            build()
        _dll = ctypes.CDLL(str(LIBRARY))
        pointer = np.ctypeslib.ndpointer(dtype=np.float64, flags="C_CONTIGUOUS")
        _dll.air400_flow.argtypes = [pointer] * 5 + [ctypes.c_double] * 2 + [ctypes.c_int] * 8
        _dll.air400_flow.restype = ctypes.c_int
    a = np.ascontiguousarray(Im1, dtype=np.float64)
    b = np.ascontiguousarray(Im2, dtype=np.float64)
    if a.shape != b.shape or a.ndim != 3 or a.shape[2] not in (1, 3):
        raise ValueError("Expected two equal HWC RGB or grayscale arrays")
    h, w, c = a.shape
    u, v = np.zeros((h, w)), np.zeros((h, w))
    warp = np.zeros((h, w, c))
    status = _dll.air400_flow(u, v, warp, a, b, alpha, ratio, minWidth,
                             nOuterFPIterations, nInnerFPIterations,
                             nSORIterations, colType, h, w, c)
    if status:
        raise RuntimeError("Original Coarse2Fine C++ function raised an exception")
    return u, v, warp


def smoke_test() -> dict:
    from scipy.ndimage import gaussian_filter
    rng = np.random.default_rng(42)
    frame = gaussian_filter(rng.random((64, 96, 3)), sigma=(1.2, 1.2, 0))
    frame = (frame - frame.min()) / np.ptp(frame)
    u0, v0, _ = coarse2fine_flow(frame, frame, .012, .75, 20, 7, 1, 30, 0)
    shifted = np.roll(frame, 2, axis=1)
    u, v, _ = coarse2fine_flow(frame, shifted, .012, .75, 20, 7, 1, 30, 0)
    stats = {"identical_max_abs": float(max(np.abs(u0).max(), np.abs(v0).max())),
             "translated_median_u": float(np.median(u[12:-12, 12:-12])),
             "translated_median_v": float(np.median(v[12:-12, 12:-12]))}
    if not all(np.isfinite(x).all() for x in (u0, v0, u, v)):
        raise AssertionError("Coarse2Fine produced non-finite values")
    if stats["identical_max_abs"] > 1e-5 or abs(stats["translated_median_u"] - 2) > .75:
        raise AssertionError(f"Coarse2Fine binding test failed: {stats}")
    return stats


def pair_worker(args):
    """One independent pair per process: upstream C++ noise parameters are static."""
    previous, current, params = args
    u, v, _ = coarse2fine_flow(previous, current, *params)
    return np.stack((u, v), axis=-1)


if __name__ == "__main__":
    if "--build" in sys.argv:
        build()
    print(json.dumps(smoke_test(), indent=2))
