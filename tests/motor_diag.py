#!/usr/bin/env python3
"""
MKS SERVO42C 诊断工具
发送各种诊断指令，看电机是否响应。
"""

import sys
import time
import struct
import serial


def checksum(data: bytes) -> int:
    return sum(data) & 0xFF


def make_cmd(addr: int, code: int, *payload: int) -> bytes:
    buf = bytes([addr, code] + list(payload))
    return buf + bytes([checksum(buf)])


def hexdump(data: bytes) -> str:
    h = data.hex().upper()
    return " ".join(h[i:i+2] for i in range(0, len(h), 2))


BAUDRATES = [15200, 9600, 19200, 38400, 57600, 115200]
PORT = "/dev/ttyAS8"
ADDR = 0xE0

for baud in BAUDRATES:
    print(f"\n{'='*60}")
    print(f"尝试波特率: {baud}")
    print(f"{'='*60}")

    try:
        ser = serial.Serial(
            port=PORT,
            baudrate=baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.5,
        )
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        # 指令 1: 读取使能状态 (0x3a)
        cmd1 = make_cmd(ADDR, 0x3A)
        print(f"\n  ① 读使能状态: {hexdump(cmd1)}")
        ser.write(cmd1)
        ser.flush()
        time.sleep(0.2)
        r1 = ser.read(64)
        print(f"    响应: {hexdump(r1) if r1 else '(无)'}")

        # 指令 2: 读取编码器值 (0x30) — 预期返回较多数据
        cmd2 = make_cmd(ADDR, 0x30)
        print(f"\n  ② 读编码器值: {hexdump(cmd2)}")
        ser.write(cmd2)
        ser.flush()
        time.sleep(0.2)
        r2 = ser.read(64)
        print(f"    响应: {hexdump(r2) if r2 else '(无)'}")

        # 指令 3: 读取实时位置 (0x36)
        cmd3 = make_cmd(ADDR, 0x36)
        print(f"\n  ③ 读实时位置: {hexdump(cmd3)}")
        ser.write(cmd3)
        ser.flush()
        time.sleep(0.2)
        r3 = ser.read(64)
        print(f"    响应: {hexdump(r3) if r3 else '(无)'}")

        # 指令 4: 读堵转状态 (0x3e)
        cmd4 = make_cmd(ADDR, 0x3E)
        print(f"\n  ④ 读堵转标志: {hexdump(cmd4)}")
        ser.write(cmd4)
        ser.flush()
        time.sleep(0.2)
        r4 = ser.read(64)
        print(f"    响应: {hexdump(r4) if r4 else '(无)'}")

        ser.close()

        # 如果 0x30 返回超过 3 字节数据，说明波特率匹配
        if r2 and len(r2) >= 5:
            print(f"\n  ★★★ 波特率 {baud} 匹配! 编码器返回了多字节数据 ★★★")
            break

    except serial.SerialException as e:
        print(f"  串口错误: {e}")
        continue

print("\n诊断完成")
