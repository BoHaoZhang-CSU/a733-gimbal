"""Preprocessing: BGR frame → NPU-compatible letterbox RGB buffer."""

import numpy as np
import cv2

# Constants matching model_config.h
LETTERBOX_ROWS = 640
LETTERBOX_COLS = 640
PAD_COLOR = (114, 114, 114)  # RGB


def bgr_to_npu_buffer(bgr: np.ndarray) -> np.ndarray:
    """Convert BGR image (H,W,3) → letterboxed RGB uint8 (640,640,3).

    Pure OpenCV path, matches C++ yolo11_pose_9_pre.cpp exactly.
    """
    h, w = bgr.shape[:2]

    # BGR → RGB (cv2 produces contiguous output)
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    # Letterbox scale
    scale = min(LETTERBOX_ROWS / h, LETTERBOX_COLS / w)
    new_w = int(round(scale * w))
    new_h = int(round(scale * h))

    # Resize (skip if same size)
    if new_w != w or new_h != h:
        rgb = cv2.resize(rgb, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

    # Padding (matches C++ copyMakeBorder exactly)
    dh = float(LETTERBOX_ROWS - new_h)
    dw = float(LETTERBOX_COLS - new_w)
    top = int(round(dh / 2.0 - 0.1))
    bot = int(round(dh / 2.0 + 0.1))
    left = int(round(dw / 2.0 - 0.1))
    right = int(round(dw / 2.0 + 0.1))

    return cv2.copyMakeBorder(rgb, top, bot, left, right,
                              cv2.BORDER_CONSTANT, value=PAD_COLOR)


def get_letterbox_scale_and_pad(img_h: int, img_w: int):
    """Return scale factor and padding offsets for coordinate mapping."""
    scale = min(LETTERBOX_ROWS / img_h, LETTERBOX_COLS / img_w)
    new_w = int(round(scale * img_w))
    new_h = int(round(scale * img_h))
    hpad = LETTERBOX_ROWS - new_h
    wpad = LETTERBOX_COLS - new_w
    return scale, wpad, hpad
