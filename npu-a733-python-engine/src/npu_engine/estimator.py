"""NPU inference estimators for all YOLO model variants.

Usage::

    from npu_engine import YOLODetector, YOLOPoseEstimator

    # Auto-detection from model structure (recommended)
    det = YOLODetector(model="yolo11s_6_uint8_a733.nb")
    pose = YOLOPoseEstimator(model="yolo11s-pose_9_uint8_a733.nb")

    results = det(frame)   # or pose(frame)
    det.close()
"""

import time
from typing import Optional

import numpy as np

from .backend import NpuContext
from .preprocess import bgr_to_npu_buffer
from .postprocess import (
    decode_dfl_detection,
    decode_dfl_pose,
    decode_dfl_seg,
    decode_anchor_detection,
    decode_point_detection,
    _rescale,
    _rescale_point,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Base class
# ═══════════════════════════════════════════════════════════════════════════════

class _BaseEstimator:
    """Shared NPU lifecycle for all estimators."""

    _auto_n_outputs: int  # expected number of outputs (set by subclass)

    def __init__(self, model: str, prob_threshold: float = 0.4,
                 nms_threshold: float = 0.45, lb_cols: int = 640, lb_rows: int = 640):
        self.prob_threshold = prob_threshold
        self.nms_threshold = nms_threshold
        self.lb_cols = lb_cols
        self.lb_rows = lb_rows
        self._ctx = NpuContext()
        self._ctx.init()
        self._ctx.load_model(model)
        self._ctx.set_inputs_outputs()
        self._n_outputs = len(self._ctx._output_buffers)

    def __call__(self, frame: np.ndarray) -> list[dict]:
        img_h, img_w = frame.shape[:2]
        pre = bgr_to_npu_buffer(frame)               # contiguous RGB letterbox
        self._ctx.upload_from_numpy(0, pre)          # upload without .tobytes()
        self._ctx.run()
        outputs = self._ctx.get_output_views()       # zero-copy numpy views
        dets = self._decode(outputs)
        result = _rescale(dets, img_h, img_w, self.lb_rows, self.lb_cols)
        self._ctx.release_output_views()              # unmap after postprocess
        return result

    def _decode(self, outputs: list[np.ndarray]) -> list[dict]:
        raise NotImplementedError

    # ── manual pipeline ──────────────────────────────────────────

    def preprocess_inplace(self, frame: np.ndarray) -> np.ndarray:
        """Return preprocessed ndarray (640,640,3) uint8 contiguous."""
        return bgr_to_npu_buffer(frame)

    def upload_raw(self, data: bytes):
        self._ctx.upload_input_direct(0, data)

    def run(self):
        self._ctx.run()

    def get_outputs(self) -> list[np.ndarray]:
        return [self._ctx.get_output_float_array(i) for i in range(self._n_outputs)]

    def postprocess(self, outputs: list[np.ndarray], img_h: int, img_w: int) -> list[dict]:
        dets = self._decode(outputs)
        return _rescale(dets, img_h, img_w, self.lb_rows, self.lb_cols)

    # ── lifecycle ────────────────────────────────────────────────

    def close(self):
        if self._ctx is None:
            return
        self._ctx.finish_network()
        self._ctx.destroy_network()
        self._ctx.destroy()
        self._ctx = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Concrete estimators
# ═══════════════════════════════════════════════════════════════════════════════

class YOLODetector(_BaseEstimator):
    """Object detection (yolo11, yolov8, yolov5).

    Auto-detects DFL (6 outputs) vs anchor-based (3 outputs) from model structure.
    Returns: [{"bbox": [x,y,w,h], "score": float, "label": int}, ...]
    """

    def _decode(self, outputs: list[np.ndarray]) -> list[dict]:
        n = len(outputs)
        if n == 3:
            return decode_anchor_detection(
                outputs, self.prob_threshold, self.nms_threshold,
                lb_cols=self.lb_cols, lb_rows=self.lb_rows)
        else:
            return decode_dfl_detection(
                outputs, self.prob_threshold, self.nms_threshold,
                self.lb_cols, self.lb_rows)


class YOLOPoseEstimator(_BaseEstimator):
    """Pose estimation (yolo11-pose, yolov8-pose).

    Returns: [{"bbox": [x,y,w,h], "score": float, "label": 0,
                "keypoints": np.ndarray (17,3) [x,y,conf]}, ...]
    """

    def _decode(self, outputs: list[np.ndarray]) -> list[dict]:
        return decode_dfl_pose(
            outputs, self.prob_threshold, self.nms_threshold,
            self.lb_cols, self.lb_rows)


class YOLOSegEstimator(_BaseEstimator):
    """Instance segmentation (yolo11-seg, yolov8-seg).

    Returns: [{"bbox": [x,y,w,h], "score": float, "label": int,
                "mask": np.ndarray (H,W) bool}, ...]
    """

    def _decode(self, outputs: list[np.ndarray]) -> list[dict]:
        return decode_dfl_seg(
            outputs, self.prob_threshold, self.nms_threshold,
            self.lb_cols, self.lb_rows)


class PointDetector(_BaseEstimator):
    """Single-point detection (custom CenterPoint model, 6 outputs).

    Returns: {"point": (x,y) original-image coords, "score": float}.
    """

    def _decode(self, outputs):
        return decode_point_detection(outputs, self.lb_cols, self.lb_rows)

    def __call__(self, frame):
        img_h, img_w = frame.shape[:2]
        pre = bgr_to_npu_buffer(frame)
        self._ctx.upload_from_numpy(0, pre)
        self._ctx.run()
        outputs = self._ctx.get_output_views()
        result = self._decode(outputs)
        final = _rescale_point(result, img_h, img_w, self.lb_rows, self.lb_cols)
        self._ctx.release_output_views()
        return final
