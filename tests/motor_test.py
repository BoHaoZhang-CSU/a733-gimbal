#!/usr/bin/env python3
"""
MKS SERVO42C 闭环步进电机 UART 控制测试
==========================================
使用主机串口 /dev/ttyAS8 控制两台电机（ID: 0→0xe0, 1→0xe1）

协议参考：MKS SERVO42C 闭环步进电机 使用说明 V1.1.2

接线前提（已通过电机屏幕菜单设置）：
  - Mode → CR_UART  （串口控制模式）
  - UartBaud → 15200
  - UartAddr → 0xe0 / 0xe1

安全保护：
  - 每台电机运动 ≤ 1/8 圈（3200 脉冲），防止绕线
  - Ctrl+C 时自动停止所有电机并关闭驱动
"""

import sys
import time
import struct
import serial
import signal

# ── 配置参数（按你实际硬件填写） ────────────────────────────────
SERIAL_PORT = "/dev/ttyAS8"
BAUDRATE = 115200
MOTORS = [
    {"addr": 0xE0, "label": "0"},
    {"addr": 0xE1, "label": "1"},
]
MICROSTEPS = 128

# 脉冲计算（1.8° 步进电机, 200 步/圈）
PULSES_PER_REV = 200 * MICROSTEPS          # 25600
TEST_PULSES = PULSES_PER_REV // 8          # 3200  = 1/8 圈
MOVE_SPEED = 5                              # 速度档 1-127
MOVE_TIMEOUT = 15                           # 等待电机到位超时（秒）

# ── 指令构建 ──────────────────────────────────────────────────


def checksum(data: bytes) -> int:
    """CHECKSUM 8bit: 所有字节求和取低 8 位"""
    return sum(data) & 0xFF


def make_cmd(addr: int, code: int, *payload: int) -> bytes:
    """构造一帧 MKS SERVO42C 串口指令: [addr] [code] [payload...] [cks]"""
    buf = bytes([addr, code] + list(payload))
    return buf + bytes([checksum(buf)])


def hexdump(data: bytes) -> str:
    """字节转『FF FF』格式的 hex 字符串"""
    h = data.hex().upper()
    return " ".join(h[i:i + 2] for i in range(0, len(h), 2))


# ── 电机控制类 ────────────────────────────────────────────────


class MKS42C:
    """MKS SERVO42C 闭环步进电机驱动"""

    def __init__(self, port: str, baud: int, timeout: float = 1.0):
        self.serial = serial.Serial(
            port=port,
            baudrate=baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=timeout,
            write_timeout=1,
        )
        self.serial.reset_input_buffer()
        self.serial.reset_output_buffer()
        print(f"[OK] 串口已打开: {port} @ {baud} bps")

    def close(self):
        if self.serial and self.serial.is_open:
            self.serial.close()
            print("[OK] 串口已关闭")

    # ── 底层收发 ──

    def _tx(self, cmd: bytes, tag: str = ""):
        """发送指令并打印"""
        print(f"  TX [{tag}]: {hexdump(cmd)}", flush=True)
        self.serial.write(cmd)
        self.serial.flush()

    def _rx(self, tag: str = "") -> bytes | None:
        """非阻塞读取串口缓冲中的响应并打印"""
        time.sleep(0.08)  # 等一小会儿让响应到齐
        data = self.serial.read(64)
        if data:
            print(f"  RX [{tag}]: {hexdump(data)}", flush=True)
        return data if data else None

    def _txrx(self, cmd: bytes, tag: str = "") -> bytes | None:
        """发送 + 读取一次响应"""
        self._tx(cmd, tag)
        return self._rx(tag)

    # ── 高层指令 ──

    def read_status(self, addr: int) -> bytes | None:
        """读取使能状态 (0x3a)"""
        return self._txrx(make_cmd(addr, 0x3a), f"0x{addr:02X} 状态")

    def enable(self, addr: int) -> bytes | None:
        """使能驱动 (0xf3 0x01)"""
        return self._txrx(make_cmd(addr, 0xF3, 0x01), f"0x{addr:02X} 使能")

    def disable(self, addr: int) -> bytes | None:
        """关闭驱动 (0xf3 0x00)"""
        return self._txrx(make_cmd(addr, 0xF3, 0x00), f"0x{addr:02X} 关闭")

    def stop(self, addr: int) -> bytes | None:
        """停止转动 (0xf7)"""
        return self._txrx(make_cmd(addr, 0xF7), f"0x{addr:02X} 停止")

    def move_abs(self, addr: int, speed: int, pulses: int) -> bool:
        """
        位置控制 (0xfd) — 发送后等待电机到位

        参数:
          addr:   电机地址 0xe0-0xe9
          speed:  速度档 1-127
          pulses: 脉冲数 (正=正转, 负=反转)
        返回:
          True=到位, False=超时/失败
        """
        # ── 编码参数 ──
        direction = 0x80 if pulses < 0 else 0x00
        abs_pulses = abs(pulses)
        spd_byte = direction | (speed & 0x7F)

        # 脉冲数按大端序打包为 4 字节 uint32
        pos_bytes = struct.pack(">I", abs_pulses)

        cmd = make_cmd(addr, 0xFD, spd_byte, *pos_bytes)
        tag = f"0x{addr:02X} 位置 {'+' if pulses >= 0 else '-'}{abs_pulses}"

        # ── 发送前清空缓冲 ──
        self.serial.reset_input_buffer()

        # ── 发送 ──
        self._tx(cmd, tag)

        # ── 等待完成 ──
        deadline = time.time() + MOVE_TIMEOUT
        started = False

        while time.time() < deadline:
            resp = self.serial.read(64)
            if resp:
                print(f"  RX [{tag}]: {hexdump(resp)}", flush=True)
                for i in range(len(resp) - 2):
                    # 响应格式: [addr] [01/02] [checksum]
                    if resp[i] == addr and resp[i + 1] == 0x02:
                        print(f"  ✓ 到位! ({abs_pulses} 脉冲)", flush=True)
                        return True
                    if resp[i] == addr and resp[i + 1] == 0x01:
                        started = True
            if not started:
                time.sleep(0.05)
            # 如果已经开始运动但还没有完成，继续等待
            # 注意：运动期间可能不会发回任何数据，所以不能完全依赖收到数据
            # 这里的读超时 timeot=1s 会自然阻塞

        # 超时 —— 但可能运动还在进行中，打印提示
        print(f"  ⚠ 超时 ({MOVE_TIMEOUT}s)，但电机可能仍在运动中", flush=True)
        return False


# ── 测试流程 ──────────────────────────────────────────────────


def test_one_motor(mc: MKS42C, addr: int, label: str):
    """对单台电机执行完整测试序列"""
    print(f"\n{'=' * 56}")
    print(f"  电机 {label}  (地址 0x{addr:02X})")
    print(f"{'=' * 56}")

    # Step 1 ─ 握手
    print(f"\n▶ Step 1/5: 握手 — 读取使能状态")
    resp = mc.read_status(addr)
    if not resp:
        print(f"  ⚠ 无响应，地址 0x{addr:02X} 可能不在线")
    else:
        print(f"  通信正常 ✓")

    # Step 2 ─ 使能
    print(f"\n▶ Step 2/5: 使能驱动")
    mc.enable(addr)
    time.sleep(0.3)

    # Step 3 ─ 正转 1/8 圈
    print(f"\n▶ Step 3/5: 正转 {TEST_PULSES} 脉冲 (约 1/8 圈, 速度档 {MOVE_SPEED})")
    ok = mc.move_abs(addr, MOVE_SPEED, TEST_PULSES)
    if ok:
        print(f"  正转到位 ✓")
    else:
        print(f"  正转结果不确定（可能还在走，等一会儿再反转归位）")
    time.sleep(1)  # 到位后稳定一下

    # Step 4 ─ 反转 1/8 圈归位
    print(f"\n▶ Step 4/5: 反转 {TEST_PULSES} 脉冲 归位")
    ok = mc.move_abs(addr, MOVE_SPEED, -TEST_PULSES)
    if ok:
        print(f"  归位到位 ✓")
    else:
        print(f"  归位结果不确定")
    time.sleep(0.5)

    # Step 5 ─ 关闭驱动
    print(f"\n▶ Step 5/5: 关闭驱动")
    mc.disable(addr)

    print(f"\n  ✅ 电机 {label} 测试完成")


def emergency_stop(mc: MKS42C | None):
    """安全停止 & 关闭所有电机"""
    if mc is None:
        return
    print(f"\n{'!' * 56}")
    print(f"  紧急停止 — 停止所有电机并关闭驱动")
    print(f"{'!' * 56}")
    for motor in MOTORS:
        addr = motor["addr"]
        print(f"  电机 {motor['label']} (0x{addr:02X}):")
        mc.stop(addr)
        time.sleep(0.05)
        mc.disable(addr)
        time.sleep(0.05)
    mc.close()
    print("[OK] 安全清理完成")


# ── 主入口 ────────────────────────────────────────────────────

_MC: MKS42C | None = None


def signal_handler(sig, frame):
    """捕获 SIGINT (Ctrl+C) 后安全停止"""
    print(f"\n\n[!] 捕获到信号 {sig}, 正在安全停止...")
    emergency_stop(_MC)
    sys.exit(130)


def main():
    global _MC

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    mc = MKS42C(SERIAL_PORT, BAUDRATE)
    _MC = mc

    try:
        for motor in MOTORS:
            test_one_motor(mc, motor["addr"], motor["label"])
            time.sleep(1)  # 电机间间隔

        print(f"\n{'=' * 56}")
        print(f"  全部测试完成！两台电机均已完成运动测试。")
        print(f"{'=' * 56}")

    except Exception as e:
        print(f"\n[!] 异常: {e}", flush=True)
        import traceback
        traceback.print_exc()
    finally:
        emergency_stop(mc)
        _MC = None
        sys.exit(0)


if __name__ == "__main__":
    main()
