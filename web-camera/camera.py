#!/usr/bin/env python3
"""
Camera module — 管理 USB 摄像头的帧捕获与参数调节
=================================================
在独立线程中持续从 V4L2 读取原始 MJPEG 帧，直通给浏览器，
跳过 OpenCV 的解码→缩放→再编码环节，大幅降低 CPU 消耗与延迟。
"""

import threading
import time
from typing import Callable, Optional

import cv2
import numpy as np

from v4l2_capture import (
    V4L2Capture,
    V4L2_CID_BRIGHTNESS,
    V4L2_CID_CONTRAST,
    V4L2_CID_SATURATION,
    V4L2_CID_GAIN,
    V4L2_CID_FOCUS_ABSOLUTE,
    V4L2_CID_EXPOSURE_ABSOLUTE,
    V4L2_CID_EXPOSURE_AUTO,
    V4L2_EXPOSURE_MANUAL,
)


class Camera:
    """USB 摄像头封装，后台线程持续抓帧并预编码 JPEG。"""

    # ----- 参数范围 -----
    PARAM_RANGES = {
        "brightness": (0, 255, 128),
        "contrast": (0, 255, 50),
        "saturation": (0, 255, 64),
        "gain": (0, 255, 80),
        "exposure": (0, 10000, 166),
        "focus": (0, 255, 68),
    }

    # 参数名 → V4L2 控件 ID
    V4L2_CID_MAP = {
        "brightness": V4L2_CID_BRIGHTNESS,
        "contrast": V4L2_CID_CONTRAST,
        "saturation": V4L2_CID_SATURATION,
        "gain": V4L2_CID_GAIN,
        "focus": V4L2_CID_FOCUS_ABSOLUTE,
    }

    def __init__(
        self,
        index: int = 0,
        width: int = 1920,
        height: int = 1080,
        stream_width: int = 854,
        stream_height: int = 480,
        jpeg_quality: int = 75,
    ):
        self._device = f"/dev/video{index}"
        self._target_width = width
        self._target_height = height
        # 推流用缩小的分辨率（画叠加层时使用，推流本身用原始分辨率）
        self._stream_w = stream_width
        self._stream_h = stream_height
        self._jpeg_quality = jpeg_quality

        self._v4l2: Optional[V4L2Capture] = None
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._running = False

        # 后台预编码的 JPEG 字节（V4L2 直通，无需编码！）
        self._latest_jpeg: Optional[bytes] = None
        # 原始 BGR 帧（用于拍照，仅在需要时解码）
        self._latest_raw: Optional[cv2.Mat] = None

        # 检测处理后的拼合图 JPEG
        self._composite_jpeg: Optional[bytes] = None
        self._detection_point: tuple[float, float] = (0.0, 0.0)
        self._detection_score: float = 0.0

        self._frame_ready = threading.Event()
        self._composite_ready = threading.Event()

        # 可选的外部帧处理器（由 detector 提供）
        # 签名: (raw_frame, stream_w, stream_h) -> (jpeg_bytes, (x,y), score) | None
        self._frame_processor: Optional[Callable] = None
        self._actual_w: int = 0
        self._actual_h: int = 0
        self._param_cache: dict[str, int] = {}

        # 帧率统计
        self._fps: float = 0.0

    # ---- 公共属性 ----

    @property
    def resolution(self) -> tuple[int, int]:
        return self._actual_w, self._actual_h

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def is_opened(self) -> bool:
        return self._v4l2 is not None and self._v4l2.fd >= 0

    # ---- 参数读写 ----

    def get_param(self, name: str) -> Optional[int]:
        return self._param_cache.get(name)

    def set_param(self, name: str, value: int) -> bool:
        if name not in self.PARAM_RANGES:
            return False
        lo, hi, _ = self.PARAM_RANGES[name]
        val = max(lo, min(hi, value))
        ok = False
        with self._lock:
            if self._v4l2 and self._v4l2.fd >= 0:
                if name == "exposure":
                    ok = self._v4l2.set_exposure(val)
                else:
                    cid = self.V4L2_CID_MAP.get(name)
                    if cid:
                        ok = self._v4l2.set_control(cid, val)
            self._param_cache[name] = val
        return ok

    def get_all_params(self) -> dict:
        return dict(self._param_cache)

    def reset_params(self) -> None:
        for name, (_, _, default) in self.PARAM_RANGES.items():
            self.set_param(name, default)

    # ---- 生命周期 ----

    def start(self) -> bool:
        if self._running:
            return True

        # 1) 打开 V4L2 MJPEG 直通
        v4l2 = V4L2Capture(
            device=self._device,
            width=self._target_width,
            height=self._target_height,
            nbuffers=3,
        )
        try:
            v4l2.open()
        except Exception as e:
            print(f"[Camera] V4L2 打开失败: {e}")
            return False

        self._v4l2 = v4l2
        self._actual_w = v4l2.actual_width
        self._actual_h = v4l2.actual_height
        print(f"[Camera] V4L2 直通模式: {self._actual_w}x{self._actual_h} MJPG")

        # 2) 读取初始参数
        self._init_params()

        # 3) 曝光值检查（过高会拖慢帧率）
        if self._param_cache.get("exposure", 0) > 500:
            sane_exp = 166
            self._v4l2.set_exposure(sane_exp)
            self._param_cache["exposure"] = sane_exp
            print(f"[Camera] 曝光值过高，已设为 {sane_exp} 以保证帧率")

        print(f"[Camera] 初始参数: {self._param_cache}")

        # 4) 启动抓帧线程
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        return True

    def _init_params(self) -> None:
        """从 V4L2 控件或默认值读取初始参数。"""
        for name, (lo, hi, default) in self.PARAM_RANGES.items():
            val: Optional[int] = None
            if self._v4l2 and self._v4l2.fd >= 0:
                if name == "exposure":
                    # 先切手动模式，再读值
                    self._v4l2.set_control(
                        V4L2_CID_EXPOSURE_AUTO, V4L2_EXPOSURE_MANUAL
                    )
                    val = self._v4l2.get_exposure()
                else:
                    cid = self.V4L2_CID_MAP.get(name)
                    if cid:
                        val = self._v4l2.get_control(cid)
            if val is None or val < lo or val > hi:
                val = default
                if self._v4l2 and self._v4l2.fd >= 0:
                    if name == "exposure":
                        self._v4l2.set_exposure(val)
                    else:
                        cid = self.V4L2_CID_MAP.get(name)
                        if cid:
                            self._v4l2.set_control(cid, val)
            self._param_cache[name] = val

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        with self._lock:
            if self._v4l2:
                self._v4l2.close()
                self._v4l2 = None
        print("[Camera] 已释放")

    # ---- 获取帧 ----

    def get_jpeg_stream(self) -> Optional[bytes]:
        """获取最新一帧的 JPEG 字节 —— 零拷贝/零编码。"""
        if not self._frame_ready.is_set():
            return None
        with self._lock:
            return self._latest_jpeg

    def get_raw_frame(self) -> Optional[cv2.Mat]:
        """获取原始 BGR 帧（用于保存高质量照片）。
        每次调用都会从最新 JPEG 解码，不保留副本。
        """
        jpeg = self.get_jpeg_stream()
        if jpeg is None:
            return None
        frame = cv2.imdecode(
            np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR
        )
        return frame

    # ---- 检测处理器 ----

    def set_frame_processor(self, processor: Callable) -> None:
        """注册帧处理器（如 NPU 检测 + 拼合绘制）。"""
        self._frame_processor = processor

    def get_composite_jpeg(self) -> Optional[bytes]:
        """获取最新拼合图的 JPEG 字节（含检测叠加）。"""
        if not self._composite_ready.is_set():
            return None
        with self._lock:
            return self._composite_jpeg

    def get_detection_result(self) -> dict:
        """获取最新检测结果。"""
        with self._lock:
            return {
                "point": list(self._detection_point),
                "score": round(self._detection_score, 4),
            }

    # ---- 内部抓帧循环 ----

    def _capture_loop(self) -> None:
        frame_count = 0
        fps_t0 = time.monotonic()
        _last_detection_time = 0.0
        _detect_interval = 0.10  # 10 fps 检测上限

        while self._running:
            # 1) V4L2 读取原始 MJPEG（无解码，极快）
            mjpeg = self._v4l2.read() if self._v4l2 else None
            if mjpeg is None:
                time.sleep(0.001)
                continue

            # 2) 存储为最新推流 JPEG —— 直通！
            with self._lock:
                self._latest_jpeg = mjpeg
            self._frame_ready.set()

            # 3) 如果有帧处理器（NPU 检测），节流调用
            if self._frame_processor is not None:
                now = time.monotonic()
                if now - _last_detection_time >= _detect_interval:
                    _last_detection_time = now
                    try:
                        # 解码 MJPEG → BGR（仅在检测时）
                        frame = cv2.imdecode(
                            np.frombuffer(mjpeg, dtype=np.uint8),
                            cv2.IMREAD_COLOR,
                        )
                        if frame is None:
                            continue

                        # 存储一份原始帧（供拍照用）
                        with self._lock:
                            self._latest_raw = frame.copy()

                        result = self._frame_processor(
                            frame, self._stream_w, self._stream_h
                        )
                        if result is not None:
                            comp_jpeg, pt, sc = result
                            if comp_jpeg is not None:
                                with self._lock:
                                    self._composite_jpeg = comp_jpeg
                                    self._detection_point = pt
                                    self._detection_score = sc
                                self._composite_ready.set()
                    except Exception:
                        pass

            # 帧率统计
            frame_count += 1
            if frame_count >= 15:
                elapsed = time.monotonic() - fps_t0
                self._fps = frame_count / elapsed if elapsed > 0 else 0
                frame_count = 0
                fps_t0 = time.monotonic()


# 全局单例
_camera: Optional[Camera] = None


def get_camera() -> Camera:
    global _camera
    if _camera is None:
        _camera = Camera()
        if not _camera.start():
            raise RuntimeError("摄像头初始化失败")
    return _camera


def release_camera() -> None:
    global _camera
    if _camera:
        _camera.stop()
        _camera = None
