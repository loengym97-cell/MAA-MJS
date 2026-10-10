# -*- coding: utf-8 -*-
"""用 MaaFramework.dll 自带的 OCRer C API 验证 OCR 识别"""
import ctypes, json, sys
import numpy as np

DLL = r"D:/MAA_MJS/python/Lib/site-packages/maa/bin/MaaFramework.dll"
RES = r"D:/MAA_MJS/resource"

lib = ctypes.WinDLL(DLL)

class MaaRect(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int32), ("y", ctypes.c_int32),
                ("w", ctypes.c_int32), ("h", ctypes.c_int32)]

H = ctypes.c_void_p
MaaStatus = ctypes.c_int32

# --- Resource ---
lib.MaaResourceCreate.restype = H
lib.MaaResourcePostBundle.restype = H
lib.MaaResourcePostBundle.argtypes = [H, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_void_p]
lib.MaaResourceWait.restype = MaaStatus
lib.MaaResourceWait.argtypes = [H]
lib.MaaResourceDestroy.restype = None
lib.MaaResourceDestroy.argtypes = [H]

# --- OCRer ---
lib.MaaOCRerCreate.restype = H
lib.MaaOCRerCreate.argtypes = [H]
lib.MaaOCRerSetImage.restype = ctypes.c_bool
lib.MaaOCRerSetImage.argtypes = [H, H]
lib.MaaOCRerSetROI.restype = ctypes.c_bool
lib.MaaOCRerSetROI.argtypes = [H, MaaRect]
lib.MaaOCRerSetModel.restype = ctypes.c_bool
lib.MaaOCRerSetModel.argtypes = [H, ctypes.c_char_p]
lib.MaaOCRerSetExpected.restype = ctypes.c_bool
lib.MaaOCRerSetExpected.argtypes = [H, H]
lib.MaaOCRerAnalyze.restype = ctypes.c_bool
lib.MaaOCRerAnalyze.argtypes = [H]
lib.MaaOCRerGetResult.restype = H
lib.MaaOCRerGetResult.argtypes = [H]
lib.MaaOCRerDestroy.restype = None
lib.MaaOCRerDestroy.argtypes = [H]

# --- ImageBuffer (用 maa 包的封装) ---
sys.path.insert(0, r"D:/MAA_MJS/python/Lib/site-packages")
from maa.buffer import ImageBuffer, StringListBuffer, StringBuffer

def imread_any(p):
    import cv2
    data = np.frombuffer(open(p, "rb").read(), np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)

# 1. 加载资源（含 OCR 模型）
res = lib.MaaResourceCreate()
if not res:
    print("ResourceCreate 失败"); sys.exit(1)
job = lib.MaaResourcePostBundle(res, RES.encode("utf-8"), None, None)
status = lib.MaaResourceWait(job)
print("资源加载 status:", status, "(4=成功)")
if status != 4:
    sys.exit(1)

# 2. 读图
img = imread_any(r"D:/shot_kl.png")
print("图:", img.shape)

# 3. OCR 全图
ocr = lib.MaaOCRerCreate(res)
ib = ImageBuffer()
ib.set(img)
assert lib.MaaOCRerSetImage(ocr, ib._handle)
assert lib.MaaOCRerAnalyze(ocr)
rb = lib.MaaOCRerGetResult(ocr)
sb = StringBuffer(rb)
raw = sb.get()
print("=== 全图 OCR 结果 ===")
try:
    data = json.loads(raw)
    for item in data.get("all", []):
        print(f'  [{item["box"][0]},{item["box"][1]},{item["box"][2]-item["box"][0]}x{item["box"][3]-item["box"][1]}] {item["text"]} ({item["score"]:.3f})')
    if not data.get("all"):
        print("  (无识别结果)")
except Exception as e:
    print("解析失败:", e, raw[:200])

# 4. 限定 roi [530,490,217,81] 测试
lib.MaaOCRerSetROI(ocr, MaaRect(530, 490, 217, 81))
assert lib.MaaOCRerAnalyze(ocr)
rb = lib.MaaOCRerGetResult(ocr)
sb = StringBuffer(rb)
raw2 = sb.get()
print("=== roi[530,490,217x81] OCR 结果 ===")
try:
    data = json.loads(raw2)
    for item in data.get("all", []):
        print(f'  [{item["box"][0]},{item["box"][1]}] {item["text"]} ({item["score"]:.3f})')
    if not data.get("all"):
        print("  (无识别结果)")
except Exception as e:
    print("解析失败:", e, raw2[:200])

# 5. 测试 expected 匹配
lib.MaaOCRerSetExpected(ocr, StringListBuffer.set_list(["点击空白"]))
assert lib.MaaOCRerAnalyze(ocr)
rb = lib.MaaOCRerGetResult(ocr)
sb = StringBuffer(rb)
raw3 = sb.get()
print("=== expected=['点击空白'] 匹配结果 ===")
print(raw3[:300])

lib.MaaOCRerDestroy(ocr)
