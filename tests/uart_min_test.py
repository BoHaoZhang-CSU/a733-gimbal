import os
import time
import serial

uart = serial.Serial(
    "/dev/ttyAS8",
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

print("opened", flush=True)

try:
    n = uart.write(b"\x55")
    print(f"write returned: {n}", flush=True)
except serial.SerialTimeoutException:
    print("write timeout", flush=True)

time.sleep(0.5)

try:
    print(f"out_waiting: {uart.out_waiting}", flush=True)
    print(f"in_waiting: {uart.in_waiting}", flush=True)
except Exception as exc:
    print(f"status error: {exc}", flush=True)

# 避开 Python 主动调用 uart.close()
os._exit(0)
