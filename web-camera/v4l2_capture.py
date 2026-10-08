#!/usr/bin/env python3
"""
V4L2 MJPEG 直通采集模块
=======================================
直接从 V4L2 设备读取原始 MJPEG 缓冲区，绕过 OpenCV 的解码→再编码环节。

依赖: Python 标准库 (ctypes, mmap, fcntl, os) — 无需额外安装包。

架构说明
--------
ioctl 号从内核头文件 (`linux/videodev2.h`) 取得，在 Linux 5.15 ARM64 上验证。
ctypes 结构体通过显式填充字段对齐内核布局。
"""

import ctypes
import ctypes.util
import errno
import fcntl
import mmap
import os
from typing import Optional

libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)

# ============================================================
#  V4L2 常量
# ============================================================

V4L2_BUF_TYPE_VIDEO_CAPTURE = 1
V4L2_MEMORY_MMAP = 1
V4L2_FIELD_ANY = 0
V4L2_PIX_FMT_MJPEG = 0x47504A4D  # 'MJPG' 小端

# ——— 控件 ID ———
V4L2_CID_BRIGHTNESS = 0x00980900
V4L2_CID_CONTRAST = 0x00980901
V4L2_CID_SATURATION = 0x00980902
V4L2_CID_GAIN = 0x00980913
V4L2_CID_FOCUS_ABSOLUTE = 0x0098090A
V4L2_CID_EXPOSURE_ABSOLUTE = 0x00980911
V4L2_CID_EXPOSURE_AUTO = 0x009809C1

V4L2_EXPOSURE_MANUAL = 1
V4L2_EXPOSURE_AUTO = 0

# ============================================================
#  ioctl 请求号 — 直接从内核头文件取得（跨架构稳定性）
# ============================================================
# 这些值来自 Linux 5.15 on ARM64: /usr/include/linux/videodev2.h
# 使用硬编码而非动态计算，避免 ctypes 结构体大小与内核布局不一致的问题。

VIDIOC_QUERYCAP = 0x80685600
VIDIOC_S_FMT = 0xC0D05605
VIDIOC_REQBUFS = 0xC0145608
VIDIOC_QUERYBUF = 0xC0585609
VIDIOC_QBUF = 0xC058560F
VIDIOC_DQBUF = 0xC0585611
VIDIOC_STREAMON = 0x40045612
VIDIOC_STREAMOFF = 0x40045613
VIDIOC_G_CTRL = 0xC008561B
VIDIOC_S_CTRL = 0xC008561C
VIDIOC_QUERYCTRL = 0xC0445624

# ============================================================
#  ctypes Struct 定义 — 显式填充以匹配内核布局
# ============================================================

class v4l2_capability(ctypes.Structure):
    """匹配内核: driver(16) + card(32) + bus_info(32) + version(4)
       + capabilities(4) + device_caps(4) + reserved(12) = 104 字节"""
    _fields_ = [
        ("driver", ctypes.c_uint8 * 16),
        ("card", ctypes.c_uint8 * 32),
        ("bus_info", ctypes.c_uint8 * 32),
        ("version", ctypes.c_uint32),
        ("capabilities", ctypes.c_uint32),
        ("device_caps", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32 * 3),
    ]


class v4l2_pix_format(ctypes.Structure):
    _fields_ = [
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("pixelformat", ctypes.c_uint32),
        ("field", ctypes.c_uint32),
        ("bytesperline", ctypes.c_uint32),
        ("sizeimage", ctypes.c_uint32),
        ("colorspace", ctypes.c_uint32),
        ("priv", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("ycbcr_enc", ctypes.c_uint32),
        ("quantization", ctypes.c_uint32),
        ("xfer_func", ctypes.c_uint32),
    ]


class v4l2_format_fmt(ctypes.Union):
    """内核 union v4l2_format.fmt — 对齐 8 字节（因含指针成员）"""
    _fields_ = [
        ("pix", v4l2_pix_format),
        ("raw_data", ctypes.c_uint8 * 200),
    ]


class v4l2_format(ctypes.Structure):
    """匹配内核: type(4) + pad(4) + fmt.union(200) = 208 字节"""
    _fields_ = [
        ("type", ctypes.c_uint32),
        ("_pad", ctypes.c_uint32),  # 填充到 8 字节对齐 union
        ("fmt", v4l2_format_fmt),
    ]


class v4l2_timeval(ctypes.Structure):
    """内核 struct timeval — aarch64 上两个 s64。"""
    _fields_ = [
        ("tv_sec", ctypes.c_int64),
        ("tv_usec", ctypes.c_int64),
    ]


class v4l2_requestbuffers(ctypes.Structure):
    _fields_ = [
        ("count", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("memory", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32 * 2),
    ]


class v4l2_timecode(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("frames", ctypes.c_uint8),
        ("seconds", ctypes.c_uint8),
        ("minutes", ctypes.c_uint8),
        ("hours", ctypes.c_uint8),
        ("userbits", ctypes.c_uint8 * 4),
    ]


class v4l2_buffer_m(ctypes.Union):
    """内核 union: 最大成员为 unsigned long / 指针 (8 字节)"""
    _fields_ = [
        ("offset", ctypes.c_uint32),
        ("userptr", ctypes.c_uint64),
        ("fd", ctypes.c_int32),
    ]


class v4l2_buffer(ctypes.Structure):
    """匹配内核: 88 字节 (含自然对齐填充)"""
    _fields_ = [
        ("index", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("bytesused", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("field", ctypes.c_uint32),
        ("timestamp", v4l2_timeval),
        ("timecode", v4l2_timecode),
        ("sequence", ctypes.c_uint32),
        ("memory", ctypes.c_uint32),
        ("m", v4l2_buffer_m),
        ("length", ctypes.c_uint32),
        ("reserved2", ctypes.c_uint32),
        ("reserved", ctypes.c_int32),
    ]


class v4l2_control(ctypes.Structure):
    _fields_ = [
        ("id", ctypes.c_uint32),
        ("value", ctypes.c_int32),
    ]


class v4l2_queryctrl(ctypes.Structure):
    _fields_ = [
        ("id", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("name", ctypes.c_uint8 * 32),
        ("minimum", ctypes.c_int32),
        ("maximum", ctypes.c_int32),
        ("step", ctypes.c_int32),
        ("default_value", ctypes.c_int32),
        ("flags", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32 * 2),
    ]


# ============================================================
#  验证结构体大小
# ============================================================

assert ctypes.sizeof(v4l2_capability) == 104, (
    f"sizeof(v4l2_capability)={ctypes.sizeof(v4l2_capability)}, 期望 104"
)
assert ctypes.sizeof(v4l2_format) == 208, (
    f"sizeof(v4l2_format)={ctypes.sizeof(v4l2_format)}, 期望 208"
)
assert ctypes.sizeof(v4l2_buffer) == 88, (
    f"sizeof(v4l2_buffer)={ctypes.sizeof(v4l2_buffer)}, 期望 88"
)


# ============================================================
#  ioctl 辅助函数
# ============================================================

def _do_ioctl(fd: int, request: int, arg) -> None:
    ret = fcntl.ioctl(fd, request, arg)
    if ret == -1:
        e = ctypes.get_errno()
        raise OSError(e, errno.errorcode.get(e, f"errno {e}"))


# ============================================================
#  V4L2Capture — 主接口
# ============================================================

class BufferInfo:
    __slots__ = ("mmap", "length")

    def __init__(self, mmap_obj, length: int):
        self.mmap = mmap_obj
        self.length = length


class V4L2Capture:
    """V4L2 MJPEG 直通采集。

    用法::

        cap = V4L2Capture("/dev/video0", width=1280, height=720)
        cap.open()
        while True:
            mjpeg_bytes = cap.read()
            if mjpeg_bytes:
                ...  # 直接推流/保存
        cap.close()
    """

    def __init__(
        self,
        device: str = "/dev/video0",
        width: int = 1920,
        height: int = 1080,
        nbuffers: int = 3,
    ):
        self.device = device
        self.req_width = width
        self.req_height = height
        self.nbuffers = nbuffers

        self.fd: int = -1
        self.buffers: list[BufferInfo] = []
        self.actual_width: int = 0
        self.actual_height: int = 0

    # ---- 生命周期 ----

    def open(self) -> None:
        """打开设备、协商 MJPEG 格式、申请并映射缓冲区、开始流传输。"""
        fd = os.open(self.device, os.O_RDWR)
        self.fd = fd

        try:
            # 1) 查询能力
            caps = v4l2_capability()
            _do_ioctl(fd, VIDIOC_QUERYCAP, caps)
            if not (caps.capabilities & 0x00000001):
                raise OSError(f"{self.device} 不支持 VIDEO_CAPTURE")

            # 2) 设置 MJPEG 格式
            fmt = v4l2_format()
            fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
            fmt.fmt.pix.width = self.req_width
            fmt.fmt.pix.height = self.req_height
            fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_MJPEG
            fmt.fmt.pix.field = V4L2_FIELD_ANY
            _do_ioctl(fd, VIDIOC_S_FMT, fmt)

            self.actual_width = fmt.fmt.pix.width
            self.actual_height = fmt.fmt.pix.height
            if fmt.fmt.pix.pixelformat != V4L2_PIX_FMT_MJPEG:
                raise OSError("摄像头不支持 MJPEG 格式")

            # 3) 申请缓冲区
            req = v4l2_requestbuffers()
            req.count = self.nbuffers
            req.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
            req.memory = V4L2_MEMORY_MMAP
            _do_ioctl(fd, VIDIOC_REQBUFS, req)
            if req.count < 2:
                raise OSError("申请的 V4L2 缓冲区不足")

            # 4) 查询并 mmap 每个缓冲区
            for i in range(req.count):
                buf = v4l2_buffer()
                buf.index = i
                buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
                buf.memory = V4L2_MEMORY_MMAP
                _do_ioctl(fd, VIDIOC_QUERYBUF, buf)

                length = buf.length
                m = mmap.mmap(
                    fd,
                    length,
                    mmap.PROT_READ | mmap.PROT_WRITE,
                    mmap.MAP_SHARED,
                    offset=buf.m.offset,
                )
                self.buffers.append(BufferInfo(mmap_obj=m, length=length))

                # 初始入队
                _do_ioctl(fd, VIDIOC_QBUF, buf)

            # 5) 开始传输
            _do_ioctl(
                fd, VIDIOC_STREAMON, ctypes.c_uint32(V4L2_BUF_TYPE_VIDEO_CAPTURE)
            )

        except Exception:
            self.close()
            raise

    def read(self) -> Optional[bytes]:
        """读取一帧 MJPEG 数据。返回 JPEG 字节串；IO 失败返回 None。"""
        if self.fd < 0:
            return None

        buf = v4l2_buffer()
        buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
        buf.memory = V4L2_MEMORY_MMAP

        try:
            _do_ioctl(self.fd, VIDIOC_DQBUF, buf)
        except OSError:
            return None

        if buf.bytesused == 0:
            try:
                _do_ioctl(self.fd, VIDIOC_QBUF, buf)
            except OSError:
                pass
            return None

        bi = self.buffers[buf.index]
        jpeg_bytes = bytes(bi.mmap[: buf.bytesused])

        # 归还缓冲区给驱动
        try:
            _do_ioctl(self.fd, VIDIOC_QBUF, buf)
        except OSError:
            pass

        return jpeg_bytes

    def close(self) -> None:
        """停止流传输、解除映射、关闭设备。"""
        if self.fd >= 0:
            try:
                _do_ioctl(
                    self.fd,
                    VIDIOC_STREAMOFF,
                    ctypes.c_uint32(V4L2_BUF_TYPE_VIDEO_CAPTURE),
                )
            except OSError:
                pass

        for bi in self.buffers:
            try:
                bi.mmap.close()
            except Exception:
                pass
        self.buffers.clear()

        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *args):
        self.close()

    # ---- 摄像头参数控制 ----

    def set_control(self, cid: int, value: int) -> bool:
        """设置 V4L2 控件。"""
        if self.fd < 0:
            return False
        ctrl = v4l2_control()
        ctrl.id = cid
        ctrl.value = value
        try:
            _do_ioctl(self.fd, VIDIOC_S_CTRL, ctrl)
            return True
        except OSError:
            return False

    def get_control(self, cid: int) -> Optional[int]:
        """读取 V4L2 控件值。"""
        if self.fd < 0:
            return None
        ctrl = v4l2_control()
        ctrl.id = cid
        try:
            _do_ioctl(self.fd, VIDIOC_G_CTRL, ctrl)
            return ctrl.value
        except OSError:
            return None

    def set_exposure(self, value: int) -> bool:
        """设置曝光时间（自动切手动模式）。"""
        if self.fd < 0:
            return False
        self.set_control(V4L2_CID_EXPOSURE_AUTO, V4L2_EXPOSURE_MANUAL)
        return self.set_control(V4L2_CID_EXPOSURE_ABSOLUTE, value)

    def get_exposure(self) -> Optional[int]:
        return self.get_control(V4L2_CID_EXPOSURE_ABSOLUTE)

    def __repr__(self) -> str:
        return (
            f"<V4L2Capture {self.device} "
            f"{self.actual_width}x{self.actual_height} MJPG "
            f"fd={self.fd}>"
        )
