#!/usr/bin/env python3
"""
Web Camera — Flask MJPEG 推流 + NPU 圆心检测 + 云台追踪
========================================================
将 USB 摄像头画面 + NPU 检测结果通过网页推流到局域网，
可选启用云台追踪，让检测目标自动保持在画面中心。

用法:
    python app.py --port 5000                 # 纯检测
    python app.py --port 5000 --no-gimbal     # 关闭云台
"""

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
from flask import Flask, Response, jsonify, render_template, request

# 将项目根目录加入 sys.path（供 gimbal 模块和 NPU engine 导入）
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from camera import get_camera, release_camera, Camera

app = Flask(__name__)

PHOTO_DIR = Path(__file__).resolve().parent / "snapshots"
PHOTO_DIR.mkdir(exist_ok=True)

# ---- 全局标志 ----
ENABLE_DETECTION = False
ENABLE_GIMBAL = False          # 由 --no-gimbal 控制

# 云台对象（由 main 初始化，API 端点中使用）
_gimbal_tracker = None
_gimbal_mc = None

# ========== 网页路由 ==========


@app.route("/")
def index():
    """主页面 — 显示视频流和参数控制面板。"""
    cam = get_camera()
    w, h = cam.resolution
    params = cam.get_all_params()
    det = cam.get_detection_result()
    return render_template("index.html", width=w, height=h, params=params,
                           param_ranges=Camera.PARAM_RANGES,
                           detection=det, detection_on=ENABLE_DETECTION,
                           gimbal_on=ENABLE_GIMBAL)


# ========== MJPEG 推流 ==========


def generate_frames():
    """MJPEG 生成器：从后台预编码缓存取帧。"""
    cam = get_camera()
    while True:
        if ENABLE_DETECTION:
            jpeg = cam.get_composite_jpeg()
        else:
            jpeg = cam.get_jpeg_stream()

        if jpeg is None:
            time.sleep(0.03)
            continue
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n"
            b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n"
            b"\r\n" + jpeg + b"\r\n"
        )
        # 注: 无 sleep —— MJPEG 直通，摄像头帧率即为推流帧率


@app.route("/video_feed")
def video_feed():
    """MJPEG 视频流端点。"""
    return Response(
        generate_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


# ========== 摄像头 API ==========


@app.route("/api/snapshot", methods=["POST"])
def api_snapshot():
    """手动拍照。"""
    cam = get_camera()
    raw = cam.get_raw_frame()
    if raw is None:
        return jsonify({"ok": False, "error": "尚未获取到画面"}), 503

    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    filename = f"snapshot_{ts}.jpg"
    filepath = PHOTO_DIR / filename
    ret, jpeg = cv2.imencode(".jpg", raw, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ret:
        return jsonify({"ok": False, "error": "编码失败"}), 500
    filepath.write_bytes(jpeg)
    print(f"[Snapshot] {filename} ({len(jpeg)} bytes)")
    return jsonify({"ok": True, "filename": filename})


@app.route("/api/fps")
def api_fps():
    cam = get_camera()
    return jsonify({"ok": True, "fps": round(cam.fps, 1)})


@app.route("/api/detection")
def api_detection():
    """获取最新检测结果 + 云台状态。"""
    cam = get_camera()
    det = cam.get_detection_result()
    gimbal_status = {}
    if _gimbal_tracker is not None:
        gimbal_status = {
            "tracking": _gimbal_tracker.is_active,
            "error_x": round(_gimbal_tracker.last_error_x, 1),
            "error_y": round(_gimbal_tracker.last_error_y, 1),
            "dir_pan": _gimbal_tracker.last_dir_pan,
            "dir_tilt": _gimbal_tracker.last_dir_tilt,
        }
    return jsonify({
        "ok": True,
        "enabled": ENABLE_DETECTION,
        **det,
        "gimbal": gimbal_status,
    })


@app.route("/api/params", methods=["GET"])
def api_get_params():
    cam = get_camera()
    return jsonify({"ok": True, "params": cam.get_all_params()})


@app.route("/api/params", methods=["POST"])
def api_set_params():
    cam = get_camera()
    data = request.get_json(force=True)
    for name, value in data.items():
        if cam.set_param(name, int(value)):
            print(f"[Param] {name} = {value}")
    return jsonify({"ok": True, "params": cam.get_all_params()})


@app.route("/api/reset", methods=["POST"])
def api_reset():
    cam = get_camera()
    cam.reset_params()
    return jsonify({"ok": True, "params": cam.get_all_params()})


# ========== 云台 API ==========


@app.route("/api/gimbal/start", methods=["POST"])
def api_gimbal_start():
    """启动云台追踪。"""
    if _gimbal_tracker is None:
        return jsonify({"ok": False, "error": "云台未初始化"}), 400
    _gimbal_tracker.start()
    print("[Gimbal] 追踪已启动")
    return jsonify({"ok": True, "active": True})


@app.route("/api/gimbal/stop", methods=["POST"])
def api_gimbal_stop():
    """停止云台追踪。"""
    if _gimbal_tracker is None:
        return jsonify({"ok": False}), 200
    _gimbal_tracker.stop()
    print("[Gimbal] 追踪已停止")
    return jsonify({"ok": True, "active": False})


# ========== 入口 ==========


def main():
    parser = argparse.ArgumentParser(description="USB 摄像头 Web 推流 + 圆心检测 + 云台追踪")
    parser.add_argument("--port", type=int, default=5000, help="监听端口 (默认 5000)")
    parser.add_argument("--host", type=str, default="0.0.0.0",
                        help="监听地址 (默认 0.0.0.0)")
    parser.add_argument("--no-detect", action="store_true",
                        help="关闭 NPU 圆心检测（默认开启）")
    parser.add_argument("--no-gimbal", action="store_true",
                        help="关闭云台追踪（默认开启）")
    parser.add_argument("--debug", action="store_true", help="Flask debug 模式")
    args = parser.parse_args()

    global ENABLE_DETECTION, ENABLE_GIMBAL, _gimbal_tracker, _gimbal_mc
    ENABLE_DETECTION = not args.no_detect
    ENABLE_GIMBAL = (not args.no_gimbal) and ENABLE_DETECTION  # 无检测不追踪

    # 初始化摄像头
    cam = get_camera()
    w, h = cam.resolution

    # 初始化 NPU 检测
    detector = None
    if ENABLE_DETECTION:
        from detector import DetectionProcessor
        detector = DetectionProcessor()
        if detector.start():
            cam.set_frame_processor(detector.process)
            print(f"  🎯  圆心检测: 已启用")
        else:
            print(f"  ⚠️   圆心检测: 初始化失败（回退到纯画面推流）")
            ENABLE_DETECTION = False

    # 初始化云台追踪
    if ENABLE_GIMBAL:
        from gimbal import MKS42C, GimbalTracker
        try:
            _gimbal_mc = MKS42C("/dev/ttyAS8", 115200)
            _gimbal_tracker = GimbalTracker(_gimbal_mc, cam, debug=False)
            print(f"  🔄  云台追踪: 就绪（网页端控制启停）")
        except Exception as e:
            print(f"  ⚠️   云台初始化失败: {e}")
            ENABLE_GIMBAL = False

    try:
        print(f"\n  🌐  服务器: http://0.0.0.0:{args.port}")
        print(f"  📷  摄像头: {w}x{h}")
        if ENABLE_DETECTION:
            print(f"  🎯  检测:    ON  推流: 左=原始 | 右=检测叠加")
        else:
            print(f"  📡  推流:    MJPEG 直通 ({w}x{h})")
        if ENABLE_GIMBAL:
            print(f"  🔄  云台:    ON  目标自动居中")
        else:
            print(f"  🔄  云台:    OFF （使用 --no-gimbal 显式关闭）")
        print(f"  💻  访问:    http://<本机IP>:{args.port}")
        print()

        app.run(host=args.host, port=args.port, debug=args.debug,
                threaded=True, use_reloader=False)
    finally:
        if _gimbal_tracker is not None:
            _gimbal_tracker.stop()
        if _gimbal_mc is not None:
            _gimbal_mc.close()
        if detector is not None:
            detector.close()
        release_camera()


if __name__ == "__main__":
    main()
