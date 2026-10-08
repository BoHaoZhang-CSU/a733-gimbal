"""
Gimbal — 视觉追踪云台
======================
基于 MKS SERVO42C 电机 + A733 NPU 圆圈检测的追踪云台。
"""

from .motor import MKS42C, make_cmd, hexdump
from .tracker import GimbalTracker
from . import config

__all__ = ["MKS42C", "GimbalTracker", "config", "make_cmd", "hexdump"]
