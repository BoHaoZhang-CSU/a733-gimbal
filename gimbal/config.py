"""
Gimbal Tracking — 配置文件
==========================
所有可调参数集中管理，方便在线调参。
"""

# ── 串口 ──
SERIAL_PORT = "/dev/ttyAS8"
BAUDRATE = 115200

# ── 电机地址 ──
PAN_ADDR = 0xE0   # 电机 0 — 水平 (Pan)
TILT_ADDR = 0xE1  # 电机 1 — 俯仰 (Tilt)

# ── 画面几何 (原始分辨率，检测坐标在该空间) ──
FRAME_W = 1920
FRAME_H = 1080
CENTER_X = FRAME_W // 2   # 960
CENTER_Y = FRAME_H // 2   # 540

# ── 追踪控制参数 (比例步长) ──
# 每步脉冲数 = abs(误差) × STEP_GAIN，限制在 [STEP_MIN, STEP_MAX] 之间
# 每次都是 FD 位置控制指令，走完一步才走下一步，不会过冲
DEADBAND_PX = 15       # 死区 (像素)，此范围内认为已对准
STEP_GAIN = 0.6        # 每像素误差对应的脉冲数
STEP_MIN = 30          # 最小步长脉冲数
STEP_MAX = 800          # 最大步长脉冲数 (安全限制)
MOVE_SPEED = 60         # 每一步的运转速度 (1-127)
STEP_TIMEOUT = 1.5     # 单步等待超时 (秒)
MIN_SCORE = 0.95       # 最低检测置信度，低于此值不走步

# ── 机械方向 ──
# 若实际运动方向与预期相反，设为 True
INVERT_PAN = False
INVERT_TILT = False
