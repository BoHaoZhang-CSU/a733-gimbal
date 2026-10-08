#!/usr/bin/env python3
"""
Circle Detection module — 基于 NPU A733 的圆心检测
封装 PointDetector + 画面叠加绘制 + 左右拼合。
"""

import sys
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

# 将 NPU engine 的 src 目录加入 Python 路径
NPU_ENGINE_SRC = Path(__file__).resolve().parent.parent / "npu-a733-python-engine" / "src"
if str(NPU_ENGINE_SRC) not in sys.path:
    sys.path.insert(0, str(NPU_ENGINE_SRC))

from npu_engine import PointDetector  # noqa: E402

# 默认模型路径
DEFAULT_MODEL = (
    Path(__file__).resolve().parent.parent
    / "npu-a733-python-engine" / "model" / "best_uint8_a733.nb"
)


class DetectionProcessor:
    """NPU 圆心检测处理器。

    使用方式（作为 camera 的回调）:
        proc = DetectionProcessor()
        cam.set_frame_processor(proc.process)
    """

    def __init__(
        self,
        model_path: str | Path = DEFAULT_MODEL,
        display_h: int = 480,  # 推流高度
    ):
        self._model_path = str(model_path)
        self._disp_h = display_h
        self._detector: Optional[PointDetector] = None
        self._init_ok = False

    # ---- 生命周期 ----

    def start(self) -> bool:
        """创建 NPU 检测器。"""
        model = Path(self._model_path)
        if not model.exists():
            print(f"[Detector] 模型文件不存在: {model}")
            return False

        try:
            self._detector = PointDetector(model=self._model_path)
            self._init_ok = True
            print(f"[Detector] NPU 检测器已加载 ({model.name})")
            return True
        except Exception as e:
            print(f"[Detector] 初始化失败: {e}")
            return False

    def close(self) -> None:
        if self._detector is not None:
            try:
                self._detector.close()
            except Exception:
                pass
            self._detector = None
            self._init_ok = False
            print("[Detector] 已释放")

    @property
    def is_ready(self) -> bool:
        return self._init_ok and self._detector is not None

    # ---- 核心处理 ----

    def process(
        self, raw_frame: np.ndarray, stream_w: int, stream_h: int
    ) -> tuple[Optional[bytes], tuple[float, float], float]:
        """处理一帧：检测 → 画叠加 → 拼合 → 编码。

        Args:
            raw_frame: 原始帧 (H, W, 3) BGR
            stream_w: 推流宽度
            stream_h: 推流高度

        Returns:
            (composite_jpeg_bytes, (x, y), score)
            检测失败时 composite_jpeg_bytes 为 None
        """
        if not self.is_ready:
            return None, (0.0, 0.0), 0.0

        raw_h, raw_w = raw_frame.shape[:2]

        try:
            result = self._detector(raw_frame)
        except Exception as e:
            print(f"[Detector] 推理异常: {e}")
            return None, (0.0, 0.0), 0.0

        point = result["point"]
        score = result["score"]
        px, py = float(point[0]), float(point[1])

        # ----- 在推流尺寸的画面上画叠加 -----
        # 先把 raw 缩小到 stream 尺寸
        stream = cv2.resize(raw_frame, (stream_w, stream_h),
                            interpolation=cv2.INTER_LINEAR)

        overlay = stream.copy()

        if score > 0.0:
            # 坐标从 raw 空间缩放到 stream 空间
            sx = stream_w / raw_w
            sy = stream_h / raw_h
            spx = int(round(px * sx))
            spy = int(round(py * sy))

            color = (0, 255, 0) if score > 0.5 else (0, 255, 255)

            # 十字
            cv2.drawMarker(overlay, (spx, spy), color,
                           markerType=cv2.MARKER_CROSS, markerSize=16, thickness=2)
            # 外圈
            cv2.circle(overlay, (spx, spy), 12, color, 2)
            # 内点
            cv2.circle(overlay, (spx, spy), 4, color, -1)
            # 标签
            label = f"({px:.0f}, {py:.0f}) {score:.2f}"
            cv2.putText(overlay, label, (spx + 14, spy - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 2)

        # ----- 分割线 -----
        separator = np.full((stream_h, 2, 3), (80, 160, 255), dtype=np.uint8)

        # ----- 左右拼合: [原始 | 分割线 | 叠加] -----
        composite = np.hstack([stream, separator, overlay])

        # ----- 编码 -----
        ret, jpeg_buf = cv2.imencode(
            ".jpg", composite,
            [cv2.IMWRITE_JPEG_QUALITY, 75],
        )
        if not ret:
            return None, (px, py), score

        return jpeg_buf.tobytes(), (px, py), score
