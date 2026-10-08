"""YOLO postprocessing for all supported model variants.

Supports:
  - yolo11 / yolov8  detection, pose, segmentation  (DFL anchor-free)
  - yolov5  detection  (anchor-based)
"""

import numpy as np

# ── Constants ────────────────────────────────────────────────────────────────

NUM_POINTS = 17   # COCO keypoints


# ═══════════════════════════════════════════════════════════════════════════════
# Common utilities
# ═══════════════════════════════════════════════════════════════════════════════

def _sigmoid(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, -88.0, 88.0)
    return 1.0 / (1.0 + np.exp(-x))


def _nms(boxes: np.ndarray, scores: np.ndarray, threshold: float) -> np.ndarray:
    """Class-agnostic NMS. boxes: (N,4) [x0,y0,x1,y1], sorted by score desc."""
    if len(boxes) == 0:
        return np.array([], dtype=np.int32)

    x0, y0, x1, y1 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x1 - x0) * (y1 - y0)
    order = np.arange(len(boxes), dtype=np.int32)
    keep = []

    while len(order) > 0:
        i = order[0]
        keep.append(i)
        if len(order) == 1:
            break

        rest = order[1:]
        xx0 = np.maximum(x0[i], x0[rest]); yy0 = np.maximum(y0[i], y0[rest])
        xx1 = np.minimum(x1[i], x1[rest]); yy1 = np.minimum(y1[i], y1[rest])
        w = np.maximum(0.0, xx1 - xx0); h = np.maximum(0.0, yy1 - yy0)
        inter = w * h
        union = areas[i] + areas[rest] - inter
        iou = np.divide(inter, union, out=np.zeros_like(inter), where=union > 0)
        order = order[1 + np.where(iou <= threshold)[0]]

    return np.array(keep, dtype=np.int32)


def _rescale(results: list[dict], img_h: int, img_w: int,
             lb_rows: int = 640, lb_cols: int = 640) -> list[dict]:
    """Map letterbox coordinates back to original image coordinates."""
    scale = min(lb_rows / img_h, lb_cols / img_w)
    rw = int(round(scale * img_w))
    rh = int(round(scale * img_h))
    wpad = lb_cols - rw
    hpad = lb_rows - rh
    rx = img_w / rw
    ry = img_h / rh

    out = []
    for r in results:
        bx = r["bbox"]
        x0 = max(0.0, min((bx[0] - wpad / 2) * rx, img_w - 1))
        y0 = max(0.0, min((bx[1] - hpad / 2) * ry, img_h - 1))
        x1 = max(0.0, min((bx[2] - wpad / 2) * rx, img_w - 1))
        y1 = max(0.0, min((bx[3] - hpad / 2) * ry, img_h - 1))

        entry = {"bbox": [x0, y0, x1 - x0, y1 - y0], "score": r["score"]}

        if "keypoints" in r:
            kp = r["keypoints"].copy()
            kp[:, 0] = np.clip((kp[:, 0] - wpad / 2) * rx, 0, img_w - 1)
            kp[:, 1] = np.clip((kp[:, 1] - hpad / 2) * ry, 0, img_h - 1)
            entry["keypoints"] = kp
            entry["label"] = r.get("label", 0)

        if "mask_float" in r and "mask" in r:
            # Resize proto mask (proto_sp × proto_sp) to original image bbox
            mask_prob = r["mask_float"]  # (proto_sp, proto_sp)
            proto_sp = mask_prob.shape[0]
            scale_proto = lb_rows / proto_sp  # e.g., 640/160 = 4

            # Map letterbox bbox to proto coordinates
            px0 = max(0, int(r["bbox"][0] / scale_proto))
            py0 = max(0, int(r["bbox"][1] / scale_proto))
            px1 = min(proto_sp, int(r["bbox"][2] / scale_proto) + 1)
            py1 = min(proto_sp, int(r["bbox"][3] / scale_proto) + 1)

            # Crop proto mask to bbox region
            if px1 > px0 and py1 > py0:
                crop = mask_prob[py0:py1, px0:px1]
                # Resize to original image bbox size
                bw = max(1, int(x1 - x0))
                bh = max(1, int(y1 - y0))
                import cv2
                resized = cv2.resize(crop.astype(np.float32), (bw, bh),
                                     interpolation=cv2.INTER_LINEAR)
                entry["mask"] = resized > 0.5

        if "label" in r:
            entry["label"] = r["label"]

        out.append(entry)

    out.sort(key=lambda x: x["bbox"][2] * x["bbox"][3], reverse=True)
    return out


def _softmax_expected_value(arr_2d: np.ndarray) -> np.ndarray:
    """For each column of shape (16, M), compute E[i] = Σ(i·softmax(col)).

    Used in DFL bbox decoding. Returns (M,) float32.
    """
    a = arr_2d - arr_2d.max(axis=0, keepdims=True)
    e = np.exp(a)
    s = e.sum(axis=0)
    w = e / np.where(s > 0, s, 1.0)
    idx = np.arange(arr_2d.shape[0], dtype=np.float32).reshape(-1, 1)
    return (idx * w).sum(axis=0)


# ═══════════════════════════════════════════════════════════════════════════════
# DFL-based decoding (yolo11, yolov8)
# ═══════════════════════════════════════════════════════════════════════════════

def _dfl_proposals(stride: int, feat_grid: np.ndarray, feat_score: np.ndarray,
                   prob_thresh: float, num_classes: int,
                   lb_cols: int, lb_rows: int) -> dict:
    """Generate proposals for one feature scale (DFL anchor-free).

    feat_grid:  (64, N)  bbox regression logits
    feat_score: (C, N)  class logits (C=1 for pose, C=80 for detection)
    feat_kps:   (51, N) or None

    Returns dict with boxes (M,4), scores (M,), keypoints (M,17,3) or None,
    labels (M,), kept mask (N,) bool.
    """
    nx = lb_cols // stride; ny = lb_rows // stride
    N = nx * ny

    gy, gx = np.meshgrid(np.arange(ny, dtype=np.float32),
                         np.arange(nx, dtype=np.float32), indexing='ij')
    gx = gx.ravel(); gy = gy.ravel()

    # Scores: (C, N) or (N,)
    if feat_score.ndim == 1 or feat_score.shape[0] == 1:
        # Single-class case (pose): score is (N,)
        scores = _sigmoid(feat_score.ravel()[:N]).astype(np.float32)
        labels = np.zeros(N, dtype=np.int32)
        num_classes = 1
    else:
        # Multi-class case (detection): score is (C, N)
        scores_logit = feat_score[:, :N]
        scores = _sigmoid(scores_logit).max(axis=0).astype(np.float32)
        labels = scores_logit.argmax(axis=0).astype(np.int32)
        num_classes = scores_logit.shape[0]

    mask = scores >= prob_thresh
    if not mask.any():
        return {"boxes": np.zeros((0, 4), dtype=np.float32),
                "scores": np.zeros(0, dtype=np.float32),
                "keypoints": None, "labels": np.zeros(0, dtype=np.int32),
                "mask": mask, "grid_idx": np.zeros(0, dtype=np.int32)}

    idx = np.where(mask)[0]
    sf = scores[idx]; gl = labels[idx]
    gxf = gx[idx]; gyf = gy[idx]

    # DFL bbox: feat_grid channels 0-15:x0, 16-31:y0, 32-47:x1, 48-63:y1
    g3d = feat_grid[:, idx].reshape(4, 16, -1)  # (4, 16, M)
    x0 = (gxf + 0.5 - _softmax_expected_value(g3d[0])) * stride
    y0 = (gyf + 0.5 - _softmax_expected_value(g3d[1])) * stride
    x1 = (gxf + 0.5 + _softmax_expected_value(g3d[2])) * stride
    y1 = (gyf + 0.5 + _softmax_expected_value(g3d[3])) * stride

    return {"boxes": np.stack([x0, y0, x1, y1], axis=1),
            "scores": sf, "keypoints": None, "labels": gl,
            "mask": mask, "grid_idx": idx.astype(np.int32)}


def _dfl_keypoints(stride: int, feat_kps: np.ndarray, mask: np.ndarray,
                   gx_all: np.ndarray, gy_all: np.ndarray) -> np.ndarray:
    """Decode keypoints from feat_kps (51, N) for grid cells selected by mask.

    Fully vectorized — no per-keypoint Python loop.
    """
    idx = np.where(mask)[0]
    if len(idx) == 0:
        return np.zeros((0, NUM_POINTS, 3), dtype=np.float32)

    M = len(idx)
    fp = feat_kps[:, idx]              # (51, M)
    gx = gx_all[idx]; gy = gy_all[idx]  # (M,)

    kp = np.empty((M, NUM_POINTS, 3), dtype=np.float32)
    for k in range(NUM_POINTS):
        kp[:, k, 0] = (gx + fp[k * 3] * 2.0) * stride
        kp[:, k, 1] = (gy + fp[k * 3 + 1] * 2.0) * stride
        kp[:, k, 2] = _sigmoid(fp[k * 3 + 2])
    return kp


def decode_dfl_detection(outputs: list[np.ndarray], prob_threshold: float = 0.4,
                         nms_threshold: float = 0.45, lb_cols: int = 640,
                         lb_rows: int = 640) -> list[dict]:
    """DFL detection (yolo11 / yolov8), 6 outputs."""
    num_classes = outputs[1].shape[0]  # auto-detect from score channels
    proposals = []

    for s, (g, sc) in enumerate(zip(
        [outputs[0], outputs[2], outputs[4]],
        [outputs[1], outputs[3], outputs[5]])):
        stride = [8, 16, 32][s]
        g2d = g.reshape(64, -1)  # (64, N) even if already 2D
        r = _dfl_proposals(stride, g2d, sc, prob_threshold,
                          num_classes, lb_cols, lb_rows)
        if r["boxes"].shape[0] > 0:
            proposals.append(r)

    if not proposals:
        return []

    boxes = np.concatenate([p["boxes"] for p in proposals])
    scores = np.concatenate([p["scores"] for p in proposals])
    labels = np.concatenate([p["labels"] for p in proposals])

    order = np.argsort(-scores)
    boxes, scores, labels = boxes[order], scores[order], labels[order]
    kept = _nms(boxes, scores, nms_threshold)

    return [{"bbox": boxes[i].tolist(), "score": float(scores[i]),
             "label": int(labels[i])} for i in kept]


def decode_dfl_pose(outputs: list[np.ndarray], prob_threshold: float = 0.4,
                    nms_threshold: float = 0.45, lb_cols: int = 640,
                    lb_rows: int = 640) -> list[dict]:
    """DFL pose estimation (yolo11-pose / yolov8-pose), 9 outputs."""
    proposals = []

    for s in range(3):
        stride = [8, 16, 32][s]
        g2d = outputs[s * 3].reshape(64, -1)
        sc = outputs[s * 3 + 1]
        kp = outputs[s * 3 + 2].reshape(51, -1)

        r = _dfl_proposals(stride, g2d, sc, prob_threshold, 1, lb_cols, lb_rows)
        if r["boxes"].shape[0] > 0:
            nx = lb_cols // stride; ny = lb_rows // stride
            gy, gx = np.meshgrid(np.arange(ny, dtype=np.float32),
                                 np.arange(nx, dtype=np.float32), indexing='ij')
            r["keypoints"] = _dfl_keypoints(stride, kp, r["mask"],
                                           gx.ravel(), gy.ravel())
            proposals.append(r)

    if not proposals:
        return []

    boxes = np.concatenate([p["boxes"] for p in proposals])
    scores = np.concatenate([p["scores"] for p in proposals])
    kps = np.concatenate([p["keypoints"] for p in proposals])

    order = np.argsort(-scores)
    boxes, scores, kps = boxes[order], scores[order], kps[order]
    kept = _nms(boxes, scores, nms_threshold)

    return [{"bbox": boxes[i].tolist(), "score": float(scores[i]),
             "label": 0, "keypoints": kps[i].astype(np.float32)}
            for i in kept]


def decode_dfl_seg(outputs: list[np.ndarray], prob_threshold: float = 0.4,
                   nms_threshold: float = 0.45, lb_cols: int = 640,
                   lb_rows: int = 640) -> list[dict]:
    """DFL segmentation (yolo11-seg / yolov8-seg), 10 outputs.

    outputs[0:9] = bbox grid + class scores + mask coefficients × 3 scales
    outputs[9]   = mask prototype (32 × proto_h × proto_w flat float32)
    """
    if len(outputs) < 10:
        raise ValueError(f"Seg model expects >=10 outputs, got {len(outputs)}")

    num_classes = outputs[1].shape[0] if outputs[1].ndim > 1 else 80
    proto_raw = outputs[9]
    proto_n = proto_raw.size
    # Determine proto spatial dims: typical is 32 × 160 × 160 or 32 × H × W
    proto_ch = 32
    proto_sp = int((proto_n // proto_ch) ** 0.5)
    proto = proto_raw.reshape(proto_ch, proto_sp, proto_sp).astype(np.float32)
    proto_flat = proto.reshape(proto_ch, -1)  # (32, sp*sp)

    all_boxes, all_scores, all_labels, all_coeffs = [], [], [], []

    for s in range(3):
        stride = [8, 16, 32][s]
        g2d = outputs[s * 3].reshape(64, -1)      # bbox grid (64, N)
        sc = outputs[s * 3 + 1]                    # class scores
        mc = outputs[s * 3 + 2].reshape(-1, g2d.shape[1])  # mask coeffs (32, N)

        r = _dfl_proposals(stride, g2d, sc, prob_threshold, num_classes,
                          lb_cols, lb_rows)
        if r["boxes"].shape[0] > 0:
            all_boxes.append(r["boxes"])
            all_scores.append(r["scores"])
            all_labels.append(r["labels"])
            # Extract mask coefficients for each proposal's grid cell
            gi = r["grid_idx"]  # (M,)
            all_coeffs.append(mc[:, gi].T)  # (M, 32)

    if not all_boxes:
        return []

    boxes = np.concatenate(all_boxes)
    scores = np.concatenate(all_scores)
    labels = np.concatenate(all_labels)
    coeffs = np.concatenate(all_coeffs).astype(np.float32)

    order = np.argsort(-scores)
    boxes, scores, labels, coeffs = boxes[order], scores[order], labels[order], coeffs[order]
    kept = _nms(boxes, scores, nms_threshold)

    # Generate per-detection masks
    results = []
    for i in kept:
        c = coeffs[i]  # (32,)
        mask_logits = c @ proto_flat  # (sp*sp,)
        mask = _sigmoid(mask_logits).reshape(proto_sp, proto_sp)
        mask_bin = (mask > 0.5)

        results.append({
            "bbox": boxes[i].tolist(),
            "score": float(scores[i]),
            "label": int(labels[i]),
            "mask": mask_bin,    # (proto_sp, proto_sp) bool
            "mask_float": mask,  # (proto_sp, proto_sp) float32, for rescaling
        })

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Anchor-based decoding (yolov5)
# ═══════════════════════════════════════════════════════════════════════════════

# COCO anchors for yolov5s (3 anchors × 3 scales). Group index = stride index.
_YOLOV5_ANCHORS = [
    [10, 13, 16, 30, 33, 23],        # stride 8
    [30, 61, 62, 45, 59, 119],       # stride 16
    [116, 90, 156, 198, 373, 326],   # stride 32
]


def decode_anchor_detection(outputs: list[np.ndarray], prob_threshold: float = 0.4,
                            nms_threshold: float = 0.45, num_classes: int = 80,
                            lb_cols: int = 640, lb_rows: int = 640) -> list[dict]:
    """Anchor-based detection (yolov5), 3 fused outputs.

    Uses logit pre-filtering (like C++ desigmoid approach) to avoid
    expensive sigmoid on all grid cells. Only candidates that pass the
    logit threshold get full sigmoid + bbox decode.
    """
    all_boxes, all_scores, all_labels = [], [], []
    # desigmoid: inverse of sigmoid for threshold pre-filtering
    deprob = -np.log(max(1.0 / max(prob_threshold, 1e-7) - 1.0, 1e-7))

    for s, raw in enumerate(outputs):
        stride = [8, 16, 32][s]
        anchors = _YOLOV5_ANCHORS[s]
        feat_w = lb_cols // stride
        feat_h = lb_rows // stride
        C = num_classes
        ch_per_a = 5 + C

        data = raw.reshape(3, ch_per_a, feat_h, feat_w).astype(np.float32)

        tx = data[:, 0]; ty = data[:, 1]; tw = data[:, 2]; th = data[:, 3]
        obj_logit = data[:, 4]               # (3, H, W)
        cls_logits = data[:, 5:]             # (3, C, H, W)

        # ---- Logit pre-filter (avoid sigmoid on all C*H*W elements) ----
        cls_max_logit = cls_logits.max(axis=1)   # (3, H, W)
        cls_best = cls_logits.argmax(axis=1)      # (3, H, W)
        candidate = (obj_logit >= deprob) & (cls_max_logit >= deprob)

        if not candidate.any():
            continue

        # ---- Only decode candidates ----
        aidx, yidx, xidx = np.where(candidate)  # each (M,)
        M = len(aidx)

        # Extract candidate values
        tx_c = tx[aidx, yidx, xidx]
        ty_c = ty[aidx, yidx, xidx]
        tw_c = tw[aidx, yidx, xidx]
        th_c = th[aidx, yidx, xidx]
        obj_c = obj_logit[aidx, yidx, xidx]
        cls_c = cls_max_logit[aidx, yidx, xidx]
        label_c = cls_best[aidx, yidx, xidx]

        # Sigmoid bbox params
        dx = _sigmoid(tx_c); dy = _sigmoid(ty_c)
        dw = _sigmoid(tw_c); dh = _sigmoid(th_c)

        # Decode
        gx_c = xidx.astype(np.float32); gy_c = yidx.astype(np.float32)
        pred_cx = (dx * 2.0 - 0.5 + gx_c) * stride
        pred_cy = (dy * 2.0 - 0.5 + gy_c) * stride

        aw = np.array([anchors[0], anchors[2], anchors[4]], dtype=np.float32)
        ah = np.array([anchors[1], anchors[3], anchors[5]], dtype=np.float32)
        pred_w = dw * dw * 4.0 * aw[aidx]
        pred_h = dh * dh * 4.0 * ah[aidx]

        x0 = pred_cx - pred_w * 0.5
        y0 = pred_cy - pred_h * 0.5
        x1 = pred_cx + pred_w * 0.5
        y1 = pred_cy + pred_h * 0.5

        # Scores (sigmoid only on candidates)
        final_score = _sigmoid(obj_c) * _sigmoid(cls_c)

        # Filter by actual sigmoid score (logit pre-filter is approximate)
        keep = final_score >= prob_threshold
        if keep.any():
            all_boxes.append(np.stack([x0[keep], y0[keep], x1[keep], y1[keep]], axis=1))
            all_scores.append(final_score[keep])
            all_labels.append(label_c[keep])

    if not all_boxes:
        return []

    boxes = np.concatenate(all_boxes)
    scores = np.concatenate(all_scores)
    labels = np.concatenate(all_labels)

    order = np.argsort(-scores)
    boxes, scores, labels = boxes[order], scores[order], labels[order]
    kept = _nms(boxes, scores, nms_threshold)

    return [{"bbox": boxes[i].tolist(), "score": float(scores[i]),
             "label": int(labels[i])} for i in kept]


# ═══════════════════════════════════════════════════════════════════════════════
# Point detection decoding (custom CenterPoint model)
# ═══════════════════════════════════════════════════════════════════════════════

def decode_point_detection(outputs, lb_cols=640, lb_rows=640):
    """Decode CenterPoint 6-output model.

    outputs: [hm_8, off_8, hm_16, off_16, hm_32, off_32]
    Returns {"point": (x,y) letterbox coords, "score": float}.
    """
    best_score = -1.0
    best_point = None

    for s in range(3):
        stride = [8, 16, 32][s]
        hm_raw = outputs[s * 2]
        off_raw = outputs[s * 2 + 1]

        fw = lb_cols // stride
        fh = lb_rows // stride

        heatmap = _sigmoid(hm_raw.reshape(fh, fw).astype(np.float32))
        offset = _sigmoid(off_raw.reshape(2, fh, fw).astype(np.float32))

        fi = int(np.argmax(heatmap))
        gy, gx = fi // fw, fi % fw
        s = float(heatmap[gy, gx])

        if s > best_score:
            best_score = s
            dx = float(offset[0, gy, gx])
            dy = float(offset[1, gy, gx])
            best_point = ((gx + dx) * stride, (gy + dy) * stride)

    if best_point is None:
        return {"point": (0.0, 0.0), "score": 0.0}
    return {"point": best_point, "score": best_score}


def _rescale_point(result, img_h, img_w, lb_rows=640, lb_cols=640):
    """Map point from letterbox coords to original image coords."""
    scale = min(lb_rows / img_h, lb_cols / img_w)
    rw, rh = int(round(scale * img_w)), int(round(scale * img_h))
    wpad, hpad = lb_cols - rw, lb_rows - rh
    rx, ry = img_w / rw, img_h / rh

    px, py = result["point"]
    ox = np.clip((px - wpad / 2) * rx, 0, img_w - 1)
    oy = np.clip((py - hpad / 2) * ry, 0, img_h - 1)
    return {"point": (float(ox), float(oy)), "score": result["score"]}
