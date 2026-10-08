#!/usr/bin/env python3
"""Quick verification test for npu_engine PoseEstimator.

Runs inference on a test image and prints results.
"""

import sys
import time
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from npu_engine import PoseEstimator

MODEL = Path("/home/radxa/workspace/python/k1_dance/model/yolo11s-pose_9_uint8_a733.nb")
TEST_IMG = Path("/home/radxa/workspace/python/k1_dance/model/COCO_train2014_000000500390.jpg")


def main():
    print("=" * 60)
    print("NPU Engine — YOLO11-Pose Verification Test")
    print("=" * 60)

    # ── 1. Load model ────────────────────────────────────────
    print(f"\n[1] Loading model: {MODEL}")
    t0 = time.monotonic()
    est = PoseEstimator(str(MODEL))
    t1 = time.monotonic()
    print(f"    Init + load took: {(t1 - t0) * 1000:.1f} ms")

    # ── 2. Read test image ────────────────────────────────────
    print(f"\n[2] Test image: {TEST_IMG}")
    frame = cv2.imread(str(TEST_IMG))
    if frame is None:
        print(f"    ERROR: cannot read image")
        est.close()
        return 1
    print(f"    Size: {frame.shape[1]}x{frame.shape[0]}, dtype={frame.dtype}")

    # ── 3. Run inference ──────────────────────────────────────
    print(f"\n[3] Running inference (5 warmup + 10 timed)...")

    # Warmup
    for _ in range(5):
        est(frame)

    # Timed
    times = []
    for i in range(10):
        t0 = time.monotonic()
        results = est(frame)
        t1 = time.monotonic()
        elapsed = (t1 - t0) * 1000
        times.append(elapsed)
        print(f"    Run {i + 1:2d}: {elapsed:6.1f} ms  detections={len(results)}")

    times_arr = np.array(times)
    print(f"\n    Mean: {times_arr.mean():.1f} ms")
    print(f"    Min:  {times_arr.min():.1f} ms")
    print(f"    Max:  {times_arr.max():.1f} ms")
    print(f"    FPS:  {1000.0 / times_arr.mean():.1f}")

    # ── 4. Print results ──────────────────────────────────────
    print(f"\n[4] Results:")
    print(f"    Detections: {len(results)}")
    for i, r in enumerate(results):
        bx = r["bbox"]
        print(f"\n    [{i}] score={r['score']:.3f}  bbox=[{bx[0]:.0f},{bx[1]:.0f},{bx[2]:.0f},{bx[3]:.0f}]")
        kp = r["keypoints"]
        KP_NAMES = [
            "nose", "L-eye", "R-eye", "L-ear", "R-ear",
            "L-shoulder", "R-shoulder", "L-elbow", "R-elbow",
            "L-wrist", "R-wrist", "L-hip", "R-hip",
            "L-knee", "R-knee", "L-ankle", "R-ankle",
        ]
        for j in range(min(17, len(kp))):
            flag = " !" if kp[j][2] < 0.2 else ""
            print(f"        {KP_NAMES[j]:12s} ({kp[j][0]:7.2f}, {kp[j][1]:7.2f})  conf={kp[j][2]:.4f}{flag}")

    # ── 5. Cleanup ────────────────────────────────────────────
    print(f"\n[5] Cleanup...")
    est.close()
    print("    Done.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
