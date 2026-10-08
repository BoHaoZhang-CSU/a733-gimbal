#!/usr/bin/env python3
"""CenterPoint detection test — NPU inference + visual overlay."""

import sys
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from npu_engine import PointDetector

MODEL = PROJECT_ROOT / "model" / "best_uint8_a733.nb"
TEST_IMG = PROJECT_ROOT / "images" / "0089.jpg"
OUTPUT = PROJECT_ROOT / "output" / "point_result.jpg"
OUTPUT.parent.mkdir(exist_ok=True)


def main():
    print("=" * 50)
    print("CenterPoint Detection Test")
    print("=" * 50)

    with PointDetector(model=str(MODEL)) as det:
        frame = cv2.imread(str(TEST_IMG))
        if frame is None:
            print(f"ERROR: cannot read {TEST_IMG}")
            return 1
        print(f"Image: {frame.shape[1]}x{frame.shape[0]}")

        result = det(frame)
        x, y = result["point"]
        score = result["score"]
        print(f"Point: ({x:.1f}, {y:.1f})  score={score:.4f}")

        # ── Draw ──
        px, py = int(round(x)), int(round(y))

        # Crosshair
        color = (0, 255, 0) if score > 0.5 else (0, 255, 255)
        cv2.drawMarker(frame, (px, py), color,
                       markerType=cv2.MARKER_CROSS, markerSize=20, thickness=2)

        # Outer circle
        cv2.circle(frame, (px, py), 15, color, 2)
        cv2.circle(frame, (px, py), 5, color, -1)

        # Label
        label = f"({x:.0f}, {y:.0f}) {score:.2f}"
        cv2.putText(frame, label, (px + 20, py - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        cv2.imwrite(str(OUTPUT), frame)
        print(f"Saved: {OUTPUT}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
