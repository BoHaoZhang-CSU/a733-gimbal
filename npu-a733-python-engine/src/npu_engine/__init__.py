"""npu_engine: Allwinner NPU inference engine for YOLO models.

Supports: yolo11, yolov8 (detection / pose / segmentation), yolov5.

Usage::

    from npu_engine import YOLODetector, YOLOPoseEstimator, YOLOSegEstimator

    # Detection (yolo11, yolov8, yolov5)
    det = YOLODetector(model="yolo11s_6_uint8_a733.nb")
    results = det(frame)  # → [{"bbox": [x,y,w,h], "score": float, "label": int}]

    # Pose estimation (yolo11-pose, yolov8-pose)
    pose = YOLOPoseEstimator(model="yolo11s-pose_9_uint8_a733.nb")
    results = pose(frame)  # → [{"bbox": [x,y,w,h], "score": float, "keypoints": (17,3)}]

    # Context manager (auto-cleanup)
    with YOLODetector(model="...") as det:
        results = det(frame)
"""

from .estimator import YOLODetector, YOLOPoseEstimator, YOLOSegEstimator, PointDetector

__all__ = ["YOLODetector", "YOLOPoseEstimator", "YOLOSegEstimator", "PointDetector"]
__version__ = "0.2.0"
