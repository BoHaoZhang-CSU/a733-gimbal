"""
GimbalTracker — 视觉追踪云台控制 (比例步长模式)
================================================
从 Camera 读取检测结果，驱动 Pan/Tilt 电机将目标保持在画面中心。

控制策略: 比例步长位置控制
  - 每步脉冲数 = abs(误差) × STEP_GAIN，限制在 [STEP_MIN, STEP_MAX]
  - 每次都是 FD 位置控制指令，走完一步才走下一步
  - 误差大 → 大步，误差小 → 小步，不会过冲震荡
  - 置信度不足 → 不走步
"""

import threading
import time

from .config import (
    PAN_ADDR, TILT_ADDR,
    CENTER_X, CENTER_Y,
    DEADBAND_PX, STEP_GAIN, STEP_MIN, STEP_MAX,
    MOVE_SPEED, STEP_TIMEOUT, MIN_SCORE,
    INVERT_PAN, INVERT_TILT,
)
from .motor import MKS42C


class GimbalTracker:
    """云台追踪控制器 (比例步长)。

    用法:
        mc = MKS42C("/dev/ttyAS8", 115200)
        tracker = GimbalTracker(mc, camera)
        tracker.start()       # 开始追踪 (后台线程)
        ...
        tracker.stop()        # 停止追踪
    """

    def __init__(self, mc: MKS42C, camera, debug: bool = False):
        """
        参数:
            mc:     已打开的 MKS42C 驱动器
            camera: 具有 get_detection_result() 方法的相机对象
                    返回 {"point": [x, y], "score": float}
            debug:  是否打印电机指令日志
        """
        self.mc = mc
        self.camera = camera
        self.debug = debug

        self._running = False
        self._thread: threading.Thread | None = None

        # 追踪状态 (供外部 API 读取)
        self.last_error_x = 0.0
        self.last_error_y = 0.0
        self.last_dir_pan = 0     # -1=左, 0=停止, +1=右
        self.last_dir_tilt = 0    # -1=上, 0=停止, +1=下

    # ── 生命周期 ──

    def start(self):
        """使能电机 + 启动控制线程"""
        if self._running:
            return

        if self.debug:
            print("[Tracker] 使能电机...")
        self.mc.enable(PAN_ADDR, debug=self.debug)
        self.mc.enable(TILT_ADDR, debug=self.debug)
        time.sleep(0.2)

        self._running = True
        self._thread = threading.Thread(target=self._control_loop, daemon=True)
        self._thread.start()
        if self.debug:
            print("[Tracker] 追踪线程已启动 (固定步长模式)")

    def stop(self):
        """停止追踪 + 关闭电机"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)

        # 清空串口缓冲，避免残留数据干扰下使能指令
        self.mc.flush_buffers()
        time.sleep(0.05)

        if self.debug:
            print("[Tracker] 停止电机...")

        # 先停转，再下使能（确保 debug=True 以便排查）
        self.mc.stop(PAN_ADDR, debug=True)
        time.sleep(0.03)
        self.mc.stop(TILT_ADDR, debug=True)
        time.sleep(0.05)

        self.mc.disable(PAN_ADDR, debug=True)
        time.sleep(0.03)
        self.mc.disable(TILT_ADDR, debug=True)

        print("[Tracker] 电机关闭，可手动掰动关节", flush=True)

    @property
    def is_active(self) -> bool:
        return self._running

    # ── 控制循环 ──

    @staticmethod
    def _calc_pulses(error_px: float) -> int:
        """根据像素误差计算步长脉冲数 (比例 + 限幅)。"""
        if abs(error_px) <= DEADBAND_PX:
            return 0
        raw = int(abs(error_px) * STEP_GAIN)
        clamped = max(STEP_MIN, min(STEP_MAX, raw))
        return clamped if error_px > 0 else -clamped

    def _control_loop(self):
        """后台控制循环主逻辑"""
        while self._running:
            # 1. 读取检测结果
            det = self.camera.get_detection_result()
            score = det.get("score", 0.0)
            pt = det.get("point", [CENTER_X, CENTER_Y])

            # 2. 置信度不足 → 跳过本轮
            if score < MIN_SCORE:
                self.last_dir_pan = 0
                self.last_dir_tilt = 0
                time.sleep(0.05)
                continue

            x, y = float(pt[0]), float(pt[1])
            error_x = x - CENTER_X
            error_y = y - CENTER_Y
            self.last_error_x = error_x
            self.last_error_y = error_y

            # 3. Pan — 按比例步长走一步
            pan_pulses = self._calc_pulses(error_x)
            if INVERT_PAN:
                pan_pulses = -pan_pulses
            if pan_pulses != 0:
                self.mc.move_abs(PAN_ADDR, MOVE_SPEED, pan_pulses,
                                 timeout=STEP_TIMEOUT, debug=self.debug)
            self.last_dir_pan = 1 if pan_pulses > 0 else -1 if pan_pulses < 0 else 0

            # 4. Tilt — 按比例步长走一步
            tilt_pulses = self._calc_pulses(error_y)
            if INVERT_TILT:
                tilt_pulses = -tilt_pulses
            if tilt_pulses != 0:
                self.mc.move_abs(TILT_ADDR, MOVE_SPEED, tilt_pulses,
                                 timeout=STEP_TIMEOUT, debug=self.debug)
            self.last_dir_tilt = 1 if tilt_pulses > 0 else -1 if tilt_pulses < 0 else 0

            # 5. 如果两个轴都没动，稍微歇一下降低 CPU
            if pan_pulses == 0 and tilt_pulses == 0:
                time.sleep(0.05)
