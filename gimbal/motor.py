"""
MKS42C — MKS SERVO42C 闭环步进电机 UART 驱动
=============================================
协议参考: MKS SERVO42C 使用说明 V1.1.2 第4~5部分
"""

import threading
import time
import struct

import serial


# ── 协议工具 ──────────────────────────────────────────────────


def checksum(data: bytes) -> int:
    """CHECKSUM 8bit: 所有字节求和取低 8 位"""
    return sum(data) & 0xFF


def make_cmd(addr: int, code: int, *payload: int) -> bytes:
    """构造一帧指令: [addr] [code] [payload...] [cks]"""
    buf = bytes([addr, code] + list(payload))
    return buf + bytes([checksum(buf)])


def hexdump(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


# ── 驱动类 ────────────────────────────────────────────────────


class MKS42C:
    """对一台或多台 MKS SERVO42C 电机进行 UART 控制。

    多台电机共用同一串口总线，通过地址区分 (0xE0-0xE9)。
    """

    def __init__(self, port: str, baud: int, timeout: float = 0.5):
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
        self._lock = threading.Lock()

    def close(self):
        if self.serial and self.serial.is_open:
            self.serial.close()

    def flush_buffers(self):
        """清空串口收发缓冲，用于线程切换/停止后确保干净状态"""
        with self._lock:
            self.serial.reset_input_buffer()
            self.serial.reset_output_buffer()

    # ── 底层收发 (日志可选，线程安全) ──

    def tx(self, cmd: bytes, tag: str = "", debug: bool = True):
        """发送指令，debug=True 时打印 hex 日志"""
        if debug:
            print(f"  TX [{tag}]: {hexdump(cmd)}", flush=True)
        with self._lock:
            self.serial.write(cmd)
            self.serial.flush()

    def rx(self, tag: str = "", debug: bool = True) -> bytes | None:
        """非阻塞读响应"""
        time.sleep(0.06)
        with self._lock:
            data = self.serial.read(64)
        if data and debug:
            print(f"  RX [{tag}]: {hexdump(data)}", flush=True)
        return data if data else None

    def txrx(self, cmd: bytes, tag: str = "", debug: bool = True) -> bytes | None:
        self.tx(cmd, tag, debug)
        return self.rx(tag, debug)

    # ── 指令封装 ──

    def enable(self, addr: int, debug: bool = False):
        """使能驱动 (0xF3 0x01)"""
        return self.txrx(make_cmd(addr, 0xF3, 0x01), f"EN{addr:02X}", debug)

    def disable(self, addr: int, debug: bool = False):
        """关闭驱动 (0xF3 0x00)"""
        return self.txrx(make_cmd(addr, 0xF3, 0x00), f"DIS{addr:02X}", debug)

    def stop(self, addr: int, debug: bool = False):
        """停止连续运转 (0xF7)"""
        return self.txrx(make_cmd(addr, 0xF7), f"STP{addr:02X}", debug)

    def rotate(self, addr: int, speed: int, direction: int = 0, debug: bool = False):
        """连续运转 (0xF6)

        参数:
            addr:      电机地址 0xE0-0xE9
            speed:     速度档 1-127
            direction: 0=正转, 1=反转
        """
        spd_byte = ((direction & 1) << 7) | (speed & 0x7F)
        tag = f"ROT{addr:02X} {'+' if direction == 0 else '-'}{speed}"
        return self.txrx(make_cmd(addr, 0xF6, spd_byte), tag, debug)

    def move_abs(self, addr: int, speed: int, pulses: int,
                 timeout: float = 15, debug: bool = False) -> bool:
        """位置控制 (0xFD) — 发送后等待到位

        返回 True=到位, False=超时
        """
        direction = 0x80 if pulses < 0 else 0x00
        spd_byte = direction | (speed & 0x7F)
        pos_bytes = struct.pack(">I", abs(pulses))
        cmd = make_cmd(addr, 0xFD, spd_byte, *pos_bytes)
        tag = f"POS{addr:02X} {'+' if pulses >= 0 else '-'}{abs(pulses)}"

        self.serial.reset_input_buffer()
        self.tx(cmd, tag, debug)

        deadline = time.time() + timeout
        while time.time() < deadline:
            resp = self.serial.read(64)
            if resp:
                if debug:
                    print(f"  RX [{tag}]: {hexdump(resp)}", flush=True)
                for i in range(len(resp) - 2):
                    if resp[i] == addr and resp[i + 1] == 0x02:
                        return True
            time.sleep(0.05)
        return False

    def read_status(self, addr: int, debug: bool = False) -> bytes | None:
        """读使能状态 (0x3a)"""
        return self.txrx(make_cmd(addr, 0x3A), f"STA{addr:02X}", debug)
