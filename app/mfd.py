"""수식 위치 검출 (Pix2Text MFD 1.5, YOLO ONNX). onnxruntime 만 쓴다."""
from __future__ import annotations

import numpy as np, onnxruntime as ort
from PIL import Image

class MFD:
    def __init__(self, path, size=768):
        self.s = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
        self.size = size

    def __call__(self, img: Image.Image, thr=0.25, iou=0.45):
        img = img.convert("RGB"); W, H = img.size
        r = min(self.size / W, self.size / H)
        nw, nh = round(W * r), round(H * r)
        # 32의 배수로 맞춘 최소 패딩 (dynamic 입력)
        pw, ph = (nw + 31) // 32 * 32, (nh + 31) // 32 * 32
        canvas = Image.new("RGB", (pw, ph), (114, 114, 114))
        canvas.paste(img.resize((nw, nh), Image.BILINEAR), (0, 0))
        x = np.asarray(canvas, dtype=np.float32).transpose(2, 0, 1)[None] / 255.0
        out = self.s.run(None, {"images": x})[0][0].T  # (N, 6)
        cls = out[:, 4:].argmax(1); sc = out[:, 4:].max(1)
        k = sc > thr; out, cls, sc = out[k], cls[k], sc[k]
        b = np.stack([out[:, 0] - out[:, 2] / 2, out[:, 1] - out[:, 3] / 2,
                      out[:, 0] + out[:, 2] / 2, out[:, 1] + out[:, 3] / 2], 1) / r
        keep = nms(b, sc, iou)
        res = []
        for i in keep:
            x0, y0, x1, y1 = b[i]
            res.append({"box": [max(0, x0), max(0, y0), min(W, x1), min(H, y1)],
                        "score": float(sc[i]), "kind": ["embedding", "isolated"][cls[i]]})
        return res

def nms(b, s, thr):
    order = s.argsort()[::-1]; keep = []
    area = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    while len(order):
        i = order[0]; keep.append(i)
        xx0 = np.maximum(b[i, 0], b[order[1:], 0]); yy0 = np.maximum(b[i, 1], b[order[1:], 1])
        xx1 = np.minimum(b[i, 2], b[order[1:], 2]); yy1 = np.minimum(b[i, 3], b[order[1:], 3])
        inter = np.clip(xx1 - xx0, 0, None) * np.clip(yy1 - yy0, 0, None)
        ov = inter / (area[i] + area[order[1:]] - inter + 1e-9)
        order = order[1:][ov < thr]
    return keep
