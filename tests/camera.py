#!/usr/bin/env python3
"""
USB Camera Test — 实时预览 + 可调参数 + 自动拍照
- 显示实时画面，方便调焦
- 可调亮度、增益、曝光等参数
- 自动拍摄 10 张照片（间隔 1 秒）保存到 ./tmp/
- 按 q 退出
"""

import os
import time
import cv2

CAMERA_INDEX = 0
PHOTO_COUNT = 10
INTERVAL_SEC = 1
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tmp")

# 参数取值范围（多数 UVC 摄像头）
BRIGHTNESS_MIN, BRIGHTNESS_MAX, BRIGHTNESS_DEFAULT = 0, 255, 128
GAIN_MIN, GAIN_MAX, GAIN_DEFAULT = 0, 255, 80
CONTRAST_MIN, CONTRAST_MAX, CONTRAST_DEFAULT = 0, 255, 50
EXPOSURE_MIN, EXPOSURE_MAX, EXPOSURE_DEFAULT = 0, 10000, 550


def log(message: str) -> None:
    print(message, flush=True)


def clamp(val, lo, hi):
    return max(lo, min(hi, val))


def main() -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    log(f"照片保存目录: {OUTPUT_DIR}")

    cap = None
    try:
        log(f"打开摄像头 (index={CAMERA_INDEX}) ...")
        cap = cv2.VideoCapture(CAMERA_INDEX)

        if not cap.isOpened():
            log("错误: 无法打开摄像头。请检查 USB 摄像头是否已连接。")
            return

        # 尝试设置分辨率
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

        actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        log(f"摄像头已打开，分辨率: {actual_w}x{actual_h}")

        # ------ 读取当前参数 ------
        raw_bright = cap.get(cv2.CAP_PROP_BRIGHTNESS)
        raw_gain = cap.get(cv2.CAP_PROP_GAIN)
        raw_contrast = cap.get(cv2.CAP_PROP_CONTRAST)
        raw_exposure = cap.get(cv2.CAP_PROP_EXPOSURE)
        raw_autoexp = cap.get(cv2.CAP_PROP_AUTO_EXPOSURE)
        raw_autofocus = cap.get(cv2.CAP_PROP_AUTOFOCUS)
        raw_focus = cap.get(cv2.CAP_PROP_FOCUS)

        log(f"初始参数 — Brightness={raw_bright}  Gain={raw_gain}  Contrast={raw_contrast}")
        log(f"              Exposure={raw_exposure}  AutoExp={raw_autoexp}  Focus={raw_focus}")

        # 如果亮度<10 则自动拉到默认值
        brightness = int(raw_bright) if raw_bright > 10 else BRIGHTNESS_DEFAULT
        gain = int(raw_gain) if raw_gain > 10 else GAIN_DEFAULT
        contrast = int(raw_contrast) if raw_contrast > 10 else CONTRAST_DEFAULT
        exposure = int(raw_exposure) if raw_exposure > 0 else EXPOSURE_DEFAULT

        cap.set(cv2.CAP_PROP_BRIGHTNESS, brightness)
        cap.set(cv2.CAP_PROP_GAIN, gain)
        cap.set(cv2.CAP_PROP_CONTRAST, contrast)
        # 设为 0.25 或 0.75 来启用 auto exposure（很多 UVC 摄像头: 0=auto, 1=manual）
        if raw_autoexp == 1.0:
            cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)  # 开启 auto exposure
        cap.set(cv2.CAP_PROP_EXPOSURE, exposure)

        log(f"调整后参数 — Brightness={brightness}  Gain={gain}  Contrast={contrast}")

        # 预热
        log("预热摄像头 ...")
        for _ in range(10):
            cap.read()

        # 创建窗口
        cv2.namedWindow("Camera Preview", cv2.WINDOW_NORMAL)
        cv2.resizeWindow("Camera Preview", actual_w // 2, actual_h // 2)

        log("")
        log("=" * 55)
        log("  实时预览已启动 ｜ 观察画面调焦/调参")
        log("")
        print("    {:25s}  {:25s}".format("[B]rightness +/-", "[G]ain +/-"))
        print("    {:25s}  {:25s}".format("[C]ontrast +/-", "[E]xposure +/-"))
        print("    {:25s}  {:25s}".format("[F]ocus +/-", "  [Space] 手动拍照"))
        print("    {:25s}  {:25s}".format("[R]eset 参数", "  [Q] 退出"))
        log("")
        log("  自动拍照中，每 1 秒一张 ...")
        log("=" * 55)

        photo_count = 0
        last_capture = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                log("读取摄像头帧失败")
                break

            now = time.time()

            # 自动拍照
            if photo_count < PHOTO_COUNT and (now - last_capture) >= INTERVAL_SEC:
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                filename = f"photo_{photo_count+1:02d}_{timestamp}.jpg"
                filepath = os.path.join(OUTPUT_DIR, filename)
                success = cv2.imwrite(filepath, frame)
                if success:
                    log(f"📸 第 {photo_count+1}/{PHOTO_COUNT} 张: {filename}")
                else:
                    log(f"第 {photo_count+1} 张保存失败")
                photo_count += 1
                last_capture = now

            # 在画面上叠加信息
            display = frame.copy()
            lines = [
                f"{actual_w}x{actual_h}  |  Photo: {photo_count}/{PHOTO_COUNT}",
                f"B:{brightness}  G:{gain}  C:{contrast}  E:{exposure}",
                f"Focus:{raw_focus:.0f}",
            ]
            for i, text in enumerate(lines):
                cv2.putText(display, text, (12, 36 + i * 32),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            cv2.putText(display, "B/G/C/E/F +/-  R:reset  Space:shot  Q:quit",
                        (12, actual_h - 16),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 200, 255), 2)

            cv2.imshow("Camera Preview", display)

            # ==== 键盘控制 ====
            key = cv2.waitKey(1) & 0xFF

            if key == ord('q'):
                log("用户按 q 退出")
                break

            elif key == ord('b'):
                # B 调高亮度  |  Shift+B (大写) 调低
                brightness = clamp(brightness + 16, BRIGHTNESS_MIN, BRIGHTNESS_MAX)
                cap.set(cv2.CAP_PROP_BRIGHTNESS, brightness)
                log(f"亮度 -> {brightness}")
            elif key == ord('B'):
                brightness = clamp(brightness - 16, BRIGHTNESS_MIN, BRIGHTNESS_MAX)
                cap.set(cv2.CAP_PROP_BRIGHTNESS, brightness)
                log(f"亮度 -> {brightness}")

            elif key == ord('g'):
                gain = clamp(gain + 10, GAIN_MIN, GAIN_MAX)
                cap.set(cv2.CAP_PROP_GAIN, gain)
                log(f"增益 -> {gain}")
            elif key == ord('G'):
                gain = clamp(gain - 10, GAIN_MIN, GAIN_MAX)
                cap.set(cv2.CAP_PROP_GAIN, gain)
                log(f"增益 -> {gain}")

            elif key == ord('c'):
                contrast = clamp(contrast + 8, CONTRAST_MIN, CONTRAST_MAX)
                cap.set(cv2.CAP_PROP_CONTRAST, contrast)
                log(f"对比度 -> {contrast}")
            elif key == ord('C'):
                contrast = clamp(contrast - 8, CONTRAST_MIN, CONTRAST_MAX)
                cap.set(cv2.CAP_PROP_CONTRAST, contrast)
                log(f"对比度 -> {contrast}")

            elif key == ord('e'):
                exposure = clamp(exposure + 200, EXPOSURE_MIN, EXPOSURE_MAX)
                cap.set(cv2.CAP_PROP_EXPOSURE, exposure)
                log(f"曝光 -> {exposure}")
            elif key == ord('E'):
                exposure = clamp(exposure - 200, EXPOSURE_MIN, EXPOSURE_MAX)
                cap.set(cv2.CAP_PROP_EXPOSURE, exposure)
                log(f"曝光 -> {exposure}")

            elif key == ord('f'):
                raw_focus = clamp(raw_focus + 5, 0, 255)
                cap.set(cv2.CAP_PROP_FOCUS, raw_focus)
                log(f"焦距 -> {raw_focus:.0f}")
            elif key == ord('F'):
                raw_focus = clamp(raw_focus - 5, 0, 255)
                cap.set(cv2.CAP_PROP_FOCUS, raw_focus)
                log(f"焦距 -> {raw_focus:.0f}")

            elif key == ord('r'):
                brightness, gain, contrast = BRIGHTNESS_DEFAULT, GAIN_DEFAULT, CONTRAST_DEFAULT
                exposure = EXPOSURE_DEFAULT
                cap.set(cv2.CAP_PROP_BRIGHTNESS, brightness)
                cap.set(cv2.CAP_PROP_GAIN, gain)
                cap.set(cv2.CAP_PROP_CONTRAST, contrast)
                cap.set(cv2.CAP_PROP_EXPOSURE, exposure)
                cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)
                log("参数已重置")

            elif key == 32:  # Space
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                filename = f"manual_{timestamp}.jpg"
                filepath = os.path.join(OUTPUT_DIR, filename)
                success = cv2.imwrite(filepath, frame)
                if success:
                    log(f"📸 手动拍照: {filename}")
                else:
                    log("手动拍照保存失败")

        log("预览已关闭")

    except Exception as exc:
        log(f"错误: {type(exc).__name__}: {exc}")

    finally:
        if cap is not None and cap.isOpened():
            cap.release()
        cv2.destroyAllWindows()
        log("摄像头已释放")


if __name__ == "__main__":
    main()
