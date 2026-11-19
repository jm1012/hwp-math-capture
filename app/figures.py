"""문제 속 그림·그래프·표 위치 찾기 (PP-DocLayout_plus-L, Apache-2.0, ONNX).

레이아웃 검출 모델이 찾은 영역 중 그림(image), 표(table), 차트(chart)만 쓴다.
찾은 영역은 글자·수식 인식에서 가리고, 원본에서 잘라 한글에 그림으로 넣는다.
"""
from __future__ import annotations

import numpy as np
import onnxruntime as ort
from PIL import Image

LABELS = ["paragraph_title", "image", "text", "number", "abstract", "content", "figure_title", "formula", "table",
          "reference", "doc_title", "footnote", "header", "algorithm", "footer", "seal", "chart", "formula_number",
          "aside_text", "reference_content"]
FIGURE_KINDS = {"image", "table", "chart"}


def _area(b):
    return max(0, b[2] - b[0]) * max(0, b[3] - b[1])


def _inter(a, b):
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


class FigureDetector:
    SIZE = 800

    def __init__(self, path: str, threads: int = 0):
        so = ort.SessionOptions()
        so.log_severity_level = 3
        if threads:
            so.intra_op_num_threads = threads
        self.s = ort.InferenceSession(path, so, providers=["CPUExecutionProvider"])

    def __call__(self, img: Image.Image, thr: float = 0.5):
        """결과: [{"box": [x0, y0, x1, y1], "kind": "image"|"table"|"chart", "score": …}, …] (위→아래)"""
        img = img.convert("RGB")
        w, h = img.size
        a = np.asarray(img.resize((self.SIZE, self.SIZE), Image.BICUBIC), np.float32) / 255.0
        x = a.transpose(2, 0, 1)[None]
        feed = {"image": x, "im_shape": np.array([[self.SIZE, self.SIZE]], np.float32),
                "scale_factor": np.array([[self.SIZE / h, self.SIZE / w]], np.float32)}
        out = self.s.run(None, feed)[0]
        cand = []
        for row in out:
            cls, sc = int(row[0]), float(row[1])
            if sc < thr or not 0 <= cls < len(LABELS) or LABELS[cls] not in FIGURE_KINDS:
                continue
            b = [max(0.0, float(row[2])), max(0.0, float(row[3])), min(float(w), float(row[4])),
                 min(float(h), float(row[5]))]
            if b[2] - b[0] < 8 or b[3] - b[1] < 8:
                continue
            cand.append({"box": b, "kind": LABELS[cls], "score": sc})
        # 겹친 상자: 큰 상자가 작은 상자를 대부분 품으면 작은 것을 버림 (그림 안의 작은 그림)
        cand.sort(key=lambda c: -_area(c["box"]))
        keep = []
        for c in cand:
            if any(_inter(c["box"], k["box"]) > 0.6 * _area(c["box"]) for k in keep):
                continue
            keep.append(c)
        return sorted(keep, key=lambda c: (c["box"][1], c["box"][0]))


_CHOICE = "①②③④⑤"


def _is_body_text(val: str) -> bool:
    """그림 상자 안에서 그림이 아니라 본문으로 볼 글자: 선지 번호 ①~⑤.
    (한글 글자는 기준으로 쓰지 않음: 동전 그림의 '한국은행', '1번째 자리' 같은 그림 속 글자가 있음)"""
    return any(c in val for c in _CHOICE)


def trim_text(figs, words, lh):
    """그림 상자가 선지 줄까지 품고 있으면 그 줄을 빼고 위나 아래 큰 쪽만 남긴다.
    남는 쪽이 너무 작으면 그 그림은 버린다. figs: FigureDetector 결과, words: [{"box", "val"}] (OCR 단어)"""
    out = []
    for f in figs:
        b = list(f["box"])
        inner = [w["box"] for w in words if _is_body_text(w["val"])
                 and b[0] <= (w["box"][0] + w["box"][2]) / 2 <= b[2] and b[1] <= (w["box"][1] + w["box"][3]) / 2 <= b[3]]
        if inner:
            top = [b[0], b[1], b[2], min(t[1] for t in inner) - 2]
            bot = [b[0], max(t[3] for t in inner) + 2, b[2], b[3]]
            keep = max((top, bot), key=lambda t: t[3] - t[1])
            if keep[3] - keep[1] < max(3 * lh, 0.3 * (b[3] - b[1])):
                continue
            b = keep
        out.append(dict(f, box=b))
    return out


def crop_figure(img: Image.Image, box, pad: int = 4) -> Image.Image:
    """그림 영역을 잘라 낸다: 실제 선·글자가 있는 곳까지 줄이고 여백을 조금 남김."""
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    g = np.asarray(img.convert("L"))[max(0, y0):y1, max(0, x0):x1] < 200
    ys, xs = np.nonzero(g)
    if len(xs):
        x0, x1 = max(0, x0) + xs.min(), max(0, x0) + xs.max() + 1
        y0, y1 = max(0, y0) + ys.min(), max(0, y0) + ys.max() + 1
    W, H = img.size
    return img.crop((max(0, x0 - pad), max(0, y0 - pad), min(W, x1 + pad), min(H, y1 + pad)))
