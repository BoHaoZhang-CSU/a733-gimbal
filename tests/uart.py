#!/usr/bin/env python3

import os
import time
import serial

DEVICE = "/dev/ttyAS8"

uart = serial.Serial(
    port=DEVICE,
    baudrate=115200,
    bytesize=serial.EIGHTBITS,
    parity=serial.PARITY_NONE,
    stopbits=serial.STOPBITS_ONE,
    timeout=0,
    write_timeout=1,
    xonxoff=False,
    rtscts=False,
    dsrdtr=False,
)

uart.reset_input_buffer()
uart.reset_output_buffer()

# 一行可读的问候语
data = b"Hello from UART8! 12345 ABCDE abcde\n"

print("=" * 50, flush=True)
print(f"Serial opened: {DEVICE}", flush=True)
print(f"Sending:  {data!r}", flush=True)
print(f"Length:   {len(data)} bytes", flush=True)
print("=" * 50, flush=True)

written = uart.write(data)
print(f"write returned: {written}", flush=True)

for index in range(30):
    status = f"{index:02d}: out_waiting={uart.out_waiting}, in_waiting={uart.in_waiting}"

    if uart.in_waiting:
        received = uart.read(uart.in_waiting)
        try:
            text = received.decode("ascii")
            status += f"  >>  RX: {text!r}"
        except UnicodeDecodeError:
            status += f"  >>  RX (raw): {received!r}"
            status += f"  >>  RX (hex): {received.hex()}"

    print(status, flush=True)

    if uart.in_waiting == 0 and uart.out_waiting == 0 and index > 3:
        print("--- idle, stopping early ---", flush=True)
        break

    time.sleep(0.1)

# 绕过当前驱动中可能阻塞的 close()
os._exit(0)