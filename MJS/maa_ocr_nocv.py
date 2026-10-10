# -*- coding: utf-8 -*-
"""用 onnxruntime + PIL + numpy 跑 MAA 的 PP-OCRv6 模型（无 cv2 依赖版）"""
import numpy as np
import onnxruntime as ort
from PIL import Image

DET = r"D:/MAA_MJS/resource/model/ocr/det.onnx"
REC = r"D:/MAA_MJS/resource/model/ocr/rec.onnx"
KEYS = r"D:/MAA_MJS/resource/model/ocr/keys.txt"

with open(KEYS, "r", encoding="utf-8") as f:
    KEYS_LIST = f.read().splitlines()
print("keys:", len(KEYS_LIST), "首行 repr:", repr(KEYS_LIST[0]))

det_sess = ort.InferenceSession(DET, providers=["CPUExecutionProvider"])
rec_sess = ort.InferenceSession(REC, providers=["CPUExecutionProvider"])

MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)

def load_image(path, max_side=960):
    img = Image.open(path).convert("RGB")
    w, h = img.size
    scale = min(1.0, max_side / max(w, h))
    # PP-OCR det 要求输入宽高是 32 的倍数
    nw = int(round(w * scale / 32)) * 32
    nh = int(round(h * scale / 32)) * 32
    nw = max(nw, 32); nh = max(nh, 32)
    if (nw, nh) != (w, h):
        img = img.resize((nw, nh))
    return img, (h, w)

def det_infer(img_np):
    x = (img_np.astype(np.float32) / 255.0 - MEAN) / STD
    x = x.transpose(2, 0, 1)[None].astype(np.float32)
    out = det_sess.run(None, {"x": x})[0][0, 0]
    return out  # PP-OCRv6 det 输出已是概率图

def split_text_boxes(mask, scale_y, scale_x, min_w=6, min_h=6, gap_merge=12):
    """行投影 + 列投影切分文本块"""
    rows = mask.sum(axis=1) > 0
    boxes = []
    y = 0
    H, W = mask.shape
    while y < H:
        if not rows[y]:
            y += 1; continue
        y0 = y
        while y < H and rows[y]:
            y += 1
        y1 = y
        band = mask[y0:y1]
        cols = band.sum(axis=0) > 0
        x = 0
        while x < W:
            if not cols[x]:
                x += 1; continue
            x0 = x
            while x < W and cols[x]:
                x += 1
            x1 = x
            boxes.append((x0, y0, x1, y1))
            x = x1
    # 合并相邻框（水平间隙小）
    merged = []
    for b in sorted(boxes, key=lambda b: (b[1], b[0])):
        if merged and abs(b[1] - merged[-1][1]) < 4 and b[0] - merged[-1][2] < gap_merge:
            x0, y0, x1, y1 = merged[-1]
            merged[-1] = (min(x0, b[0]), min(y0, b[1]), max(x1, b[2]), max(y1, b[3]))
        else:
            merged.append(list(b))
    out = []
    for x0, y0, x1, y1 in merged:
        w, h = x1-x0, y1-y0
        if w < min_w or h < min_h:
            continue
        out.append((int(x0*scale_x), int(y0*scale_y), int(w*scale_x), int(h*scale_y)))
    return out

def rec_infer(img: Image.Image):
    w, h = img.size
    nw = max(1, min(1024, int(round(w * 48.0 / h))))
    img = img.resize((nw, 48))
    arr = np.asarray(img, np.float32) / 255.0
    arr = (arr - 0.5) / 0.5  # PP-OCR rec 传统归一化
    arr = arr.transpose(2, 0, 1)[None].astype(np.float32)
    probs = rec_sess.run(None, {"x": arr})[0][0]
    idx = probs.argmax(axis=1)
    chars, prev = [], -1
    for i in idx:
        if i != prev and 0 < i < len(KEYS_LIST) - 2:  # index0=blank占位, 末尾2个=blank/space
            chars.append(KEYS_LIST[i])
        prev = i
    return "".join(chars).strip()

def ocr_image(path, roi=None):
    img, (oh, ow) = load_image(path)
    arr = np.asarray(img)
    ph = det_infer(arr)
    mask = (ph > 0.3).astype(np.uint8)
    # 1x1 轻膨胀（仅合并相邻笔画）
    k = 1
    mask2 = np.zeros_like(mask)
    H, W = mask.shape
    for dy in range(-k, k+1):
        for dx in range(-k, k+1):
            sy, sx = max(0, dy), max(0, dx)
            ey, ex = H+min(0, dy), W+min(0, dx)
            mask2[sy:ey, sx:ex] |= mask[max(0,-dy):H-max(0,dy), max(0,-dx):W-max(0,dx)]
    mask = mask2
    scale_x = ow / W; scale_y = oh / H
    boxes = split_text_boxes(mask, scale_y, scale_x)
    results = []
    for (x, y, w, h) in boxes:
        crop = img.crop((x, y, x+w, y+h))
        text = rec_infer(crop)
        if text:
            results.append((text, x, y, w, h))
    return results

if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else r"D:/shot_kl.png"
    print("识别:", path)
    results = ocr_image(path)
    print(f"共 {len(results)} 个文本:")
    for t, x, y, w, h in sorted(results, key=lambda r: (r[2]//25, r[1])):
        flag = ""
        if 490 <= y <= 571 and 530 <= x <= 747:
            flag = "  <== 在点击空白roi内"
        print(f"  [{x},{y},{w}x{h}] {t}{flag}")
