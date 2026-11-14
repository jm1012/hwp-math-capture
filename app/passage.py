"""글자 + 수식이 섞인 지문 인식.

1. 수식 위치 검출 (MFD)
2. 수식 박스 가장자리에 붙은 한글 글자는 잘라냄 (OCR 글자 위치 + 끝부분 재인식)
3. 수식 부분을 흰색으로 가리고 한글 OCR (PaddleOCR 한국어)
4. 수식 조각은 MFR 로 LaTeX 인식
5. 위치로 줄을 묶고 왼쪽→오른쪽으로 이어 붙인 뒤, 줄바꿈된 문장은 한 문단으로 합침

결과: 문단 목록. 문단은 [("text", "함수 "), ("math", "f(x)=x^2"), ...]
"""
from __future__ import annotations

import re
import time

import numpy as np
from PIL import Image, ImageDraw

from latex_fix import clean_latex, fix_choices, single_letters, split_tail

HANGUL_RUN = re.compile(r"[가-힣ㄱ-ㅎ]+")


def _area(b):
    return max(0, b[2] - b[0]) * max(0, b[3] - b[1])


def _inter(a, b):
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


class PassageReader:
    def __init__(self, mfd, mfr, ocr_det: str, ocr_rec: str, ocr_dict: str, scale_to: int = 1000):
        from rapidocr import RapidOCR
        from rapidocr.ch_ppocr_rec import TextRecInput
        self.mfd, self.mfr, self.scale_to = mfd, mfr, scale_to
        self.ocr = RapidOCR(params={
            "Global.use_cls": False, "Global.log_level": "error",
            "Det.model_path": ocr_det, "Rec.model_path": ocr_rec, "Rec.rec_keys_path": ocr_dict})
        self._TextRecInput = TextRecInput
        self.timing = (0.0, 0.0, 0.0)

    # ------------------------------------------------------------ 부품
    def _words(self, img):
        r = self.ocr(np.asarray(img)[:, :, ::-1], return_word_box=True)
        out = []
        for line in (r.word_results or []):
            for txt, _sc, box in line:
                xs = [p[0] for p in box]; ys = [p[1] for p in box]
                out.append({"box": [min(xs), min(ys), max(xs), max(ys)], "val": txt})
        return out

    def _rec_one(self, img, box):
        crop = img.crop(tuple(int(v) for v in box))
        r = self.ocr.text_rec(self._TextRecInput(img=[np.asarray(crop)[:, :, ::-1]]))
        return (r.txts[0].strip(), float(r.scores[0])) if r.txts else ("", 0.0)

    def _formulas(self, img):
        fs = self.mfd(img)
        drop = set()
        for i, f in enumerate(fs):  # 겹친 박스: 작은 것 2개 이상을 품은 큰 박스는 버리고, 1개만 품으면 안쪽을 버림
            inner = [j for j, g in enumerate(fs) if j != i and _inter(g["box"], f["box"]) > 0.8 * _area(g["box"])]
            if len(inner) >= 2:
                drop.add(i)
            elif len(inner) == 1:
                drop.add(inner[0])
        return [f["box"] for i, f in enumerate(fs) if i not in drop]

    @staticmethod
    def _hangul_spans(w, cw):
        v = w["val"]; x0, y0, x1, y1 = w["box"]
        if not HANGUL_RUN.search(v):
            return []
        if HANGUL_RUN.fullmatch(v):
            return [(x0, x1, y0, y1)]
        out = []
        for m in HANGUL_RUN.finditer(v):
            n = m.end() - m.start()
            if m.end() == len(v):
                out.append((x1 - n * cw, x1, y0, y1))
            elif m.start() == 0:
                out.append((x0, x0 + n * cw, y0, y1))
            else:
                L = len(v); out.append((x0 + (x1 - x0) * m.start() / L, x0 + (x1 - x0) * m.end() / L, y0, y1))
        return out

    def _trim_edges(self, img, b, cw):
        """수식 박스 끝에 한글 글자(의, 이, 인 …)가 붙어 있으면 잘라낸다."""
        b = list(b)
        if b[3] - b[1] > 2.5 * cw:
            return b
        for side in (1, -1):
            for _ in range(2):
                if b[2] - b[0] < 1.6 * cw:
                    break
                seg = [b[2] - 1.15 * cw, b[1], b[2], b[3]] if side == 1 else [b[0], b[1], b[0] + 1.15 * cw, b[3]]
                t, sc = self._rec_one(img, seg)
                if sc > 0.7 and t and HANGUL_RUN.fullmatch(t):
                    if side == 1:
                        b[2] -= cw
                    else:
                        b[0] += cw
                else:
                    break
        return b

    # ------------------------------------------------------------ 전체
    def __call__(self, img: Image.Image):
        img = img.convert("RGB")
        s = max(1.0, self.scale_to / img.width)
        if s > 1:
            img = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
        t0 = time.time()
        fboxes = self._formulas(img)
        ws = self._words(img)
        hs = sorted(w["box"][3] - w["box"][1] for w in ws if HANGUL_RUN.search(w["val"]))
        lh = hs[len(hs) // 2] if hs else 30
        cws = sorted((w["box"][2] - w["box"][0]) / len(w["val"]) for w in ws
                     if HANGUL_RUN.fullmatch(w["val"]) and len(w["val"]) >= 2)
        cw = cws[len(cws) // 2] if cws else 0.75 * lh

        boxes = []
        for b in fboxes:
            h = b[3] - b[1]
            if h > 2.2 * lh:  # 여러 줄짜리 수식(cases, 큰 시그마 등)은 그대로
                boxes.append(b); continue
            spans = sorted(sp for w in ws for sp in self._hangul_spans(w, cw)
                           if b[0] <= (sp[0] + sp[1]) / 2 <= b[2] and b[1] <= (sp[2] + sp[3]) / 2 <= b[3])
            x = b[0]
            for s0, s1, *_ in spans + [(b[2], b[2])]:
                if s0 - x > 0.3 * h:
                    boxes.append([x, b[1], s0, b[3]])
                x = max(x, s1)
        boxes = [self._trim_edges(img, b, cw) for b in boxes]
        boxes = [b for b in boxes if b[2] - b[0] > 4]
        t1 = time.time()

        masked = img.copy(); d = ImageDraw.Draw(masked)
        for b in boxes:
            d.rectangle(b, fill="white")
        items = [{"box": w["box"], "kind": "text", "val": w["val"]} for w in self._words(masked)]
        t2 = time.time()
        crops = [img.crop(tuple(int(v) for v in b)) for b in boxes]
        for b, latex in zip(boxes, self.mfr(crops) if crops else []):
            latex, tail = split_tail(clean_latex(latex))
            items.append({"box": b, "kind": "math", "val": latex})
            if tail:  # 수식 오른쪽 끝 바로 뒤에 글자로 둔다
                items.append({"box": [b[2] - 1, b[1], b[2], b[3]], "kind": "text", "val": tail})
        self.timing = (t1 - t0, t2 - t1, time.time() - t2)

        lines = [single_letters(fix_choices(segs)) for segs in merge_lines(items)]
        return to_paragraphs(lines)


# ------------------------------------------------------------ 줄 묶기, 문단 만들기
def merge_lines(items):
    """위치로 줄을 묶고, 줄 안에서는 왼쪽→오른쪽. 띄운 간격이 크면 공백을 넣는다."""
    items = sorted(items, key=lambda it: (it["box"][1] + it["box"][3]) / 2)
    lines = []
    for it in items:
        y0, y1 = it["box"][1], it["box"][3]
        for ln in lines:
            ov = min(y1, ln["y1"]) - max(y0, ln["y0"])
            if ov > 0.5 * min(y1 - y0, ln["y1"] - ln["y0"]):
                ln["items"].append(it); ln["y0"] = min(ln["y0"], y0); ln["y1"] = max(ln["y1"], y1)
                break
        else:
            lines.append({"y0": y0, "y1": y1, "items": [it]})
    out = []
    for ln in sorted(lines, key=lambda l: l["y0"]):
        its = sorted(ln["items"], key=lambda it: it["box"][0])
        hs = sorted(it["box"][3] - it["box"][1] for it in its if it["kind"] == "text") or \
            [it["box"][3] - it["box"][1] for it in its]
        h = hs[len(hs) // 2]
        segs, prev = [], None
        for it in its:
            if prev is not None and it["box"][0] - prev["box"][2] > 0.25 * h:
                segs.append(("text", " "))
            segs.append((it["kind"], it["val"]))
            prev = it
        out.append(_tidy(segs))
    return out


def _tidy(segs):
    """같은 종류끼리 붙이고, 줄 앞뒤 공백 정리"""
    out = []
    for k, v in segs:
        if out and k == "text" and out[-1][0] == "text":
            out[-1] = ("text", out[-1][1] + v)
        else:
            out.append((k, v))
    if out and out[0][0] == "text":
        out[0] = ("text", out[0][1].lstrip())
    if out and out[-1][0] == "text":
        out[-1] = ("text", out[-1][1].rstrip())
    return [s for s in out if s[1] != ""]


_NEW_PARA = re.compile(r"^\s*(\d+\s*[.)]|[①-⑳•·※]|\(단|<|\[|[ㄱ-ㅎ]\.|\([가-하]\))")
_END = re.compile(r"[.?!:\]]\s*$|(다|오|요)\.?\s*$")


def _plain(segs):
    return "".join(v for k, v in segs if k == "text")


def to_paragraphs(lines):
    """줄바꿈된 문장은 한 문단으로 합친다. 따로 쓴 수식, 보기, 번호로 시작하는 줄은 새 문단."""
    paras = []
    prev_alone = True
    for segs in lines:
        if not segs:
            continue
        math_only = all(k == "math" or not v.strip() for k, v in segs)
        start_new = (not paras or prev_alone or math_only or _NEW_PARA.match(_plain(segs) or "")
                     or (paras and _ends_sentence(paras[-1])))
        if start_new:
            paras.append(list(segs))
        else:
            last = paras[-1]
            joiner = ("text", " ")
            paras[-1] = _tidy(last + [joiner] + list(segs))
        prev_alone = math_only or _plain(segs).lstrip().startswith(("①", "•"))
    return paras


def _ends_sentence(segs):
    k, v = segs[-1]
    return k == "text" and bool(_END.search(v))


def to_markdown(paras) -> str:
    """다른 프로그램용 글자: 수식은 $…$ 로 감쌈"""
    return "\n".join("".join(v if k == "text" else f"${v}$" for k, v in p) for p in paras)
