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

from latex_fix import (clean_latex, fix_choices, o_after_math, single_letters, split_i, split_tail, unify_choices,
                       zero_to_o)

_TAIL_O = re.compile(r"^(.*\S)\s+(?:O|o|\\mathrm\s*\{\s*O\s*\}|\\circ)\s*$", re.S)

HANGUL_RUN = re.compile(r"[가-힣ㄱ-ㅎ]+")


def _area(b):
    return max(0, b[2] - b[0]) * max(0, b[3] - b[1])


def _inter(a, b):
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


CHOICE_MARKS = "①②③④⑤"
JAMO_HEAD = re.compile(r"^[7ㄱ¬LㄴlICcEㄷㄹ=]\s*[.,·]")


def _leftmost(w, ws):
    """같은 줄에서 가장 왼쪽 단어인지"""
    y0, y1 = w["box"][1], w["box"][3]
    for o in ws:
        if o is w or o["box"][0] >= w["box"][0]:
            continue
        ov = min(y1, o["box"][3]) - max(y0, o["box"][1])
        if ov > 0.5 * min(y1 - y0, o["box"][3] - o["box"][1]):
            return False
    return True


def _ink_box(gray, b, th=160, pad=2):
    """박스를 실제 글자(검은 점)가 있는 곳까지 줄인다. 비어 있으면 None"""
    x0, y0, x1, y1 = (int(round(v)) for v in b)
    a = gray[max(0, y0):y1, max(0, x0):x1] < th
    ys, xs = np.nonzero(a)
    if len(xs) < 6:
        return None
    return [max(0, x0) + xs.min() - pad, max(0, y0) + ys.min() - pad, max(0, x0) + xs.max() + pad + 1,
            max(0, y0) + ys.max() + pad + 1]


def _split_at_rules(boxes, gray, lh):
    """수식 박스를 가로지르는 긴 가로줄(조건 상자 테두리 등: 박스 양옆 밖까지 이어짐)에서 위아래로 나눔.
    분수 막대는 박스 밖으로 나가지 않으므로 건드리지 않음"""
    H, W = gray.shape
    out = []
    for b in boxes:
        x0, y0, x1, y1 = (int(round(v)) for v in b)
        ext = max(4, int(0.6 * lh))
        if y1 - y0 < 1.5 * lh or x0 - ext < 0 or x1 + ext > W:
            out.append(b); continue
        rows = (gray[max(0, y0):min(H, y1), x0 - ext:x1 + ext] < 160).mean(axis=1)
        cut = [y0 + i for i, r in enumerate(rows) if r > 0.97 and 0.3 * lh < i < (y1 - y0) - 0.3 * lh]
        if not cut:
            out.append(b); continue
        a, c = min(cut), max(cut)
        for part in ([x0, y0, x1, a - 1], [x0, c + 2, x1, y1]):
            t = _ink_box(gray, part)
            if t and t[3] - t[1] > 0.3 * lh:
                out.append(t)
    return out


_ARRAY2 = re.compile(r"\\begin\{(?:array\}\s*\{\s*c\s*\}|matrix\}|smallmatrix\})\s*"
                     r"((?:[^{}\\&]|\\[A-Za-z]+|\\[^\\]|\{(?:[^{}]|\{[^{}]*\})*\})+?)\s*\\\\\s*"
                     r"((?:[^{}\\&]|\\[A-Za-z]+|\\[^\\]|\{(?:[^{}]|\{[^{}]*\})*\})+?)\s*(?:\\\\\s*)?\\end\{(?:array|matrix|smallmatrix)\}")


def _has_bar(gray, cw):
    """그림에 분수 막대(위아래가 빈 짧은 가로줄)가 있나"""
    ink = gray < 160
    H, W = ink.shape
    for y in range(2, H - 2):
        row = ink[y]
        d = np.diff(np.concatenate([[0], row.astype(np.int8), [0]]))
        for a, e in zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]):
            if e - a >= 1.2 * cw and not ink[max(0, y - 3), a:e].all() and not ink[min(H - 1, y + 3), a:e].all() \
                    and ink[max(0, y - 2):y + 3, a:e].sum(axis=0).max() <= 4:
                return True
    return False


def _array_to_frac(latex, gray, cw):
    """한 칸짜리 두 줄 배열(array{c}, matrix)은 분수 막대를 놓친 분수인 경우가 많음: 그림에 분수 막대가 있으면 \\frac 로.
    (막대가 없으면 진짜 배열·이항계수일 수 있으므로 그대로)"""
    if "&" in latex or not _ARRAY2.search(latex):
        return latex
    try:
        if not _has_bar(gray, cw):
            return latex
    except Exception:  # noqa: BLE001
        return latex
    return _ARRAY2.sub(lambda m: "\\frac{" + m.group(1).strip() + "}{" + m.group(2).strip() + "}", latex, count=1)


# 수학 시험지에 자주 나오는 낱말을 OCR 이 비슷한 글자로 잘못 읽은 것 (받침·모음 하나 차이)
_WORD_FIX = [("수럼", "수렴"), ("최슷", "최솟"), ("최댄", "최댓"), ("슷자", "숫자")]


_NOT_MATH = re.compile(r"\\(?:newcommand|renewcommand|def|put|line|multiput|qbezier|begin\s*\{\s*picture|usepackage|documentclass|"
                       r"label|ref|cite|footnote|section|item|hline|includegraphics)\b")


def _hallucinated(latex, width, cw):
    """수식 인식 결과가 지어낸 것인가: 수식에 쓰지 않는 명령, 같은 조각의 반복('\\L \\L \\L …'),
    그림 폭에 비해 터무니없이 긴 결과"""
    if _NOT_MATH.search(latex):
        return True
    toks = [t for t in re.findall(r"\\[A-Za-z]+|\\.|[^\s{}]", latex) if t not in ("\\,", "\\;", "\\!", "\\ ", "\\:", "\\quad", "\\qquad")]
    for n in (1, 2, 3, 4, 5, 6, 8, 10, 12):  # n 개 토큰 묶음이 연달아 5번 이상
        for i in range(0, max(0, len(toks) - 5 * n + 1)):
            seg = toks[i:i + n]
            if all(toks[i + k * n:i + (k + 1) * n] == seg for k in range(1, 5)) and not all(re.fullmatch(r"[0-9.]", x) for x in seg):
                return True
    return len(toks) > 6 * max(1.0, width / max(cw, 1)) + 10


def _attach_scripts(segs):
    """위·아래 첨자로 시작하는 수식('^2 g(c)')은 바로 앞 글자 조각('(ln 2)', 한글 없음)의 첨자: 그 조각을 수식 앞으로 옮김"""
    out = []
    for k, v in segs:
        if k == "math" and re.match(r"\s*[\^_]", v) and out and out[-1][0] == "text":
            m = re.search(r"(\([^()가-힣]{1,12}\)|[A-Za-z0-9]{1,6})$", out[-1][1].rstrip())
            if m and out[-1][1].rstrip() == out[-1][1].rstrip()[:m.start()] + m.group(1):
                tok = m.group(1)
                rest = out[-1][1].rstrip()[:m.start()]
                tok = re.sub(r"\bln\b", r"\\ln", tok)
                out[-1] = ("text", rest)
                if not rest:
                    out.pop()
                v = tok + " " + v.lstrip()
        out.append((k, v))
    return out


def _fix_words(v):
    for a, b in _WORD_FIX:
        if a in v:
            v = v.replace(a, b)
    return v


def _rule_rows(gray, width, frac=0.4):
    """그림을 가로지르는 긴 가로줄(상자 테두리)의 y 들. 줄마다 가장 긴 잉크 줄기가 폭의 frac 이상"""
    ink = gray < 160
    cand = np.nonzero(ink.mean(axis=1) >= frac)[0]
    out = []
    for y in cand.tolist():
        row = ink[y]
        d = np.diff(np.concatenate([[0], row.astype(np.int8), [0]]))
        st, en = np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]
        if len(st) and (en - st).max() >= frac * width:
            if out and y - out[-1][1] <= 2:
                out[-1][1] = y
            else:
                out.append([y, y])
    return [(a + b) / 2 for a, b in out]


def _cut_marks(b, marks):
    """수식 박스가 보기 번호 동그라미를 품고 있으면 동그라미 자리에서 잘라 여러 박스로 나눈다.
    (보기 줄 전체, 또는 두 줄짜리 보기를 수식 하나로 잡은 경우). 결과: 박스 목록"""
    inside = [m["box"] for m in marks if _inter(b, m["box"]) > 0.5 * _area(m["box"])]
    if not inside:
        return [list(b)]
    rows = []  # 동그라미를 줄별로 묶음
    for mb in sorted(inside, key=lambda m: (m[1] + m[3]) / 2):
        cy, h = (mb[1] + mb[3]) / 2, mb[3] - mb[1]
        if rows and abs(cy - rows[-1]["cy"]) < 0.5 * h:
            rows[-1]["ms"].append(mb)
        else:
            rows.append({"cy": cy, "h": h, "ms": [mb]})
    out = []
    for i, r in enumerate(rows):
        y0 = b[1] if i == 0 else (rows[i - 1]["cy"] + r["cy"]) / 2
        y1 = b[3] if i == len(rows) - 1 else (r["cy"] + rows[i + 1]["cy"]) / 2
        x = b[0]
        for mb in sorted(r["ms"]) + [[b[2], 0, b[2], 0]]:
            if mb[0] - x > 4:
                out.append([x, y0, mb[0], y1])
            x = max(x, mb[2])
    return out


class PassageReader:
    def __init__(self, mfd, mfr, ocr_det: str, ocr_rec: str, ocr_dict: str, scale_to: int = 1000, figures=None):
        from rapidocr import RapidOCR
        from rapidocr.ch_ppocr_rec import TextRecInput
        self.mfd, self.mfr, self.scale_to = mfd, mfr, scale_to
        self.figures = figures  # 그림·표 찾기 (없으면 그림 처리 안 함)
        base = {"Global.use_cls": False, "Global.log_level": "error",
                "Det.model_path": ocr_det, "Rec.model_path": ocr_rec, "Rec.rec_keys_path": ocr_dict}
        # 첫 번째 OCR (수식 박스 속 한글 위치 찾기): 기본값(짧은 변 736 이상으로 키움). 크게 볼수록 수식 박스를 정확히 자름
        self.ocr = RapidOCR(params=base)
        # 두 번째 OCR (수식을 가린 그림의 글자): 긴 변 960. 기본값은 가로 3000px 넘게 키워 느리고 한글도 더 틀림
        self.ocr_text = RapidOCR(params={**base, "Det.limit_type": "max", "Det.limit_side_len": 960})
        self._TextRecInput = TextRecInput
        try:
            from spacing import Spacer
            self.spacer = Spacer()
        except Exception:  # noqa: BLE001  띄어쓰기 모델이 없으면 OCR 띄어쓰기 그대로
            self.spacer = None
        self.timing = (0.0, 0.0, 0.0)

    # ------------------------------------------------------------ 부품
    def _words(self, img, text_pass=False):
        r = (self.ocr_text if text_pass else self.ocr)(np.asarray(img)[:, :, ::-1], return_word_box=True)
        out = []
        for line in (r.word_results or []):
            # 보통 줄 = [(글자, 점수, 네 꼭짓점), …]. 가끔 빈 항목이나, 단어 하나짜리 줄이 (글자, 점수, 꼭짓점)
            # 그대로 나옴 (예전엔 여기서 오류가 나 인식이 멈춤)
            if isinstance(line, (tuple, list)) and len(line) == 3 and isinstance(line[0], str):
                line = [line]
            for item in line:
                if not isinstance(item, (tuple, list)) or len(item) != 3 or not isinstance(item[0], str) \
                        or item[2] is None or len(item[2]) == 0:
                    continue
                txt, _sc, box = item
                xs = [p[0] for p in box]; ys = [p[1] for p in box]
                out.append({"box": [min(xs), min(ys), max(xs), max(ys)], "val": txt})
        return out

    def rec_image(self, crop):
        """작은 그림 한 줄을 글자 인식만 (검출 없이) → (글자, 점수)"""
        if self.ocr.text_rec is None:
            self.ocr._load_rec_model()
        r = self.ocr.text_rec(self._TextRecInput(img=[np.asarray(crop.convert("RGB"))[:, :, ::-1]]))
        return (r.txts[0].strip(), float(r.scores[0])) if r.txts else ("", 0.0)

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
        if HANGUL_RUN.fullmatch(v) or re.fullmatch(r"[(\[<〈]\s*[가-힣]{1,2}\s*[)\]>〉]", v):
            return [(x0, x1, y0, y1)]  # 한글 낱말, 조건 머리 "(가)" 는 괄호까지 글자
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

    def _trim_edges(self, img, b, cw, sides=(1, -1)):
        """수식 박스 끝에 한글 글자(의, 이, 인 …)가 붙어 있거나 걸쳐 있으면 잘라낸다.
        박스 끝이 글자 중간에 걸친 경우를 위해 창을 조금씩 밖으로 밀어 가며 읽는다."""
        b = list(b)
        if b[3] - b[1] > 2.5 * cw:
            return b
        g = getattr(self, "_gray", None)
        W = img.width
        for side in sides:
            for _ in range(2):
                if b[2] - b[0] < 1.0 * cw:
                    break
                best = None
                for d in (0.0, 0.2, 0.4, 0.6, 0.8):
                    if side == 1:
                        x1 = min(W, b[2] + d * cw); seg = [x1 - 1.15 * cw, b[1], x1, b[3]]
                    else:
                        x0 = max(0, b[0] - d * cw); seg = [x0, b[1], x0 + 1.15 * cw, b[3]]
                    if d and g is not None:  # 밖으로 민 창: 박스 끝 바로 밖에 잉크가 이어져 있을 때만
                        e = int(b[2] if side == 1 else b[0])
                        band = g[int(b[1]):int(b[3]), max(0, e - 2):min(W, e + 3)] < 160
                        if not band.any():
                            break
                    t, sc = self._rec_one(img, seg)
                    if sc > (0.7 if d == 0 else 0.85) and t and HANGUL_RUN.fullmatch(t) and len(t) == 1:
                        if best is None or sc > best[0]:
                            best = (sc, seg, t)
                if best is None:
                    break
                seg = best[1]
                if side == 1:
                    b[2] = seg[2] - cw
                    glyph = [b[2], b[1], seg[2], b[3]]
                else:
                    b[0] = seg[0] + cw
                    glyph = [seg[0], b[1], b[0], b[3]]
                self._trimmed.append((glyph, best[2]))
        return b

    def _trim_tall(self, img, b, cw, ws=()):
        """키 큰 수식(시그마, 분수 등) 끝에 한글이 걸쳐 있으면, 그 글자 높이의 띠만 보고 끝을 자른다.
        (_trim_edges 는 박스 전체 높이로 글자를 읽어서 키 큰 박스에서는 한글을 못 읽음)
        띠 = 박스 끝 바로 바깥 한 글자 폭 안에서 잉크가 있는 줄 범위."""
        if b[3] - b[1] <= 2.5 * cw:
            return b
        b = list(b); g = self._gray; H, W = g.shape
        y0, y1 = max(0, int(b[1])), min(H, int(b[3]))
        for side in (1, -1):
            e = int(b[2] if side == 1 else b[0])
            xa, xb = (e, min(W, int(e + 0.9 * cw))) if side == 1 else (max(0, int(e - 0.9 * cw)), e)
            if xb - xa < 0.5 * cw:
                continue
            ys = np.nonzero((g[y0:y1, xa:xb] < 160).any(axis=1))[0]
            if len(ys) == 0:
                continue
            # 가장 긴 이어진 줄 묶음 = 옆 글자
            runs, s = [], ys[0]
            for a, c in zip(ys, list(ys[1:]) + [None]):
                if c is None or c - a > 3:
                    runs.append((s, a)); s = c
            r0, r1 = max(runs, key=lambda r: r[1] - r[0])
            if not (0.6 * cw <= r1 - r0 + 1 <= 1.7 * cw):
                continue
            band = self._trim_edges(img, [b[0], y0 + r0 - 2, b[2], y0 + r1 + 3], cw, sides=(side,))
            if side == 1:
                b[2] = min(b[2], band[2])
            else:
                b[0] = max(b[0], band[0])
        return b

    def _korean_piece(self, img, b):
        """한글 자리에서 나눈 수식 박스 조각이 실은 한글 글(첫 OCR 이 놓침)이면 그 글, 아니면 None.
        스캔본에서 '값을 구하시오. [3점]' 전체를 수식으로 잡고 한글 일부만 OCR 된 경우"""
        t, sc = self._rec_one(img, b)
        t = t.strip()
        if sc < 0.8 or not t or not HANGUL_RUN.search(t):
            return None
        rest = re.sub(r"\[\s*\d+(?:\.\d+)?\s*점\s*\]|[가-힣\s.,?!()\[\]]", "", t)
        return t if not rest else None

    def _split_tall_at_hangul(self, b, ws, cw, gray):
        """키 큰 수식 박스(분수·지수 등) 가운데에 한글 낱말이 끼어 있으면("f(x)=(1/5)^x 이고 f(f(x))=3x")
        그 낱말 자리에서 나눈다. 수식 인식기는 한글을 못 읽어 쓰레기 기호가 됨.
        낱말 세로 띠의 위·아래가 비어 있을 때만 (분수 막대 등이 지나가면 수식 일부이므로 안 나눔)"""
        spans = sorted(sp for w in ws for sp in self._hangul_spans(w, cw)
                       if b[0] < (sp[0] + sp[1]) / 2 < b[2] and b[1] <= (sp[2] + sp[3]) / 2 <= b[3])
        H, W = gray.shape
        y0, y1 = max(0, int(b[1])), min(H, int(b[3]))
        out, x = [], b[0]
        for s0, s1, t0, t1 in spans:
            if s0 - b[0] < 0.5 * cw or b[2] - s1 < 0.5 * cw:  # 박스 끝에 붙은 글자는 _trim_edges 몫
                continue
            col = gray[y0:y1, max(0, int(s0)):min(W, int(s1))] < 160
            band = np.zeros(col.shape[0], bool)
            band[max(0, int(t0) - y0 - 2):max(0, int(t1) - y0 + 3)] = True
            if col[~band].sum() > 0.02 * col.size:
                continue
            if s0 - x > 0.3 * cw:
                t = _ink_box(gray, [x, b[1], s0, b[3]])
                if t:
                    out.append(t)
            x = max(x, s1)
        if not out:
            return [b]
        t = _ink_box(gray, [x, b[1], b[2], b[3]])
        return out + ([t] if t else [])

    def _split_cases(self, b, ws, cw, lh, gray):
        """여러 줄 수식(구간별 함수 등)의 조건 칸에 한글이 있으면 줄별로 나눈다.
        수식 인식기는 한글을 못 읽어 "(aₙ이 홀수인 경우)" 가 쓰레기 기호가 되므로,
        조건 칸을 줄마다 [수식 조각 / 한글] 로 나눠 따로 읽고 나중에 cases 수식 하나로 다시 합친다.
        결과: None(해당 없음) 또는 {"box", "left", "rows": [{"band": (y0, y1), "maths": [박스…]}], "cond": 박스}"""
        H, W = gray.shape
        inside = [w for w in ws if b[0] - cw <= (w["box"][0] + w["box"][2]) / 2
                  and b[1] <= (w["box"][1] + w["box"][3]) / 2 <= b[3]]
        hw = sorted((w for w in inside if HANGUL_RUN.search(w["val"]) and (w["box"][0] + w["box"][2]) / 2 <= b[2] + cw),
                    key=lambda w: w["box"][1] + w["box"][3])
        if sum(len(m.group(0)) for w in hw for m in HANGUL_RUN.finditer(w["val"])) < 2:
            return None
        groups = []
        for w in hw:  # 한글이 있는 줄끼리 묶음
            cy = (w["box"][1] + w["box"][3]) / 2
            if groups and cy - groups[-1]["cy"] < 0.6 * lh:
                groups[-1]["ws"].append(w)
            else:
                groups.append({"cy": cy, "ws": [w]})
        xs = []
        for g in groups:  # 조건의 시작 = 그 줄 첫 한글 앞에서 "(" 로 시작하는 낱말 중 가장 오른쪽 것
            y0 = min(w["box"][1] for w in g["ws"]); y1 = max(w["box"][3] for w in g["ws"])
            first = min(sp[0] for w in g["ws"] for sp in self._hangul_spans(w, cw))
            cands = [w["box"][0] for w in inside if y0 <= (w["box"][1] + w["box"][3]) / 2 <= y1
                     and w["val"].lstrip().startswith("(") and w["box"][0] <= first]
            if not cands:
                return None
            xs.append(max(cands))
        if max(xs) - min(xs) > 1.5 * cw:
            return None
        cx0 = int(min(xs) - 4)
        if cx0 - b[0] < 2 * cw:
            return None
        cx1 = b[2]
        for g in groups:  # 조건이 수식 칸 밖으로 이어지면(긴 조건) 이어진 낱말 끝까지
            y0 = min(w["box"][1] for w in g["ws"]); y1 = max(w["box"][3] for w in g["ws"])
            x = max(w["box"][2] for w in g["ws"])
            for w in sorted((w for w in inside if y0 <= (w["box"][1] + w["box"][3]) / 2 <= y1), key=lambda w: w["box"][0]):
                if w["box"][0] > x - cw and w["box"][0] - x < 1.5 * cw:
                    x = max(x, w["box"][2])
            cx1 = max(cx1, x + 2)
        cx1 = int(min(W, cx1))
        y0, y1 = max(0, int(b[1])), min(H, int(b[3]))
        ys = np.nonzero((gray[y0:y1, cx0:cx1] < 160).any(axis=1))[0]
        if len(ys) == 0:
            return None
        bands, st = [], ys[0]
        for a, c in zip(ys, list(ys[1:]) + [None]):  # 잉크가 있는 줄 묶음 (분수의 위아래처럼 좁은 틈은 한 줄)
            if c is None or c - a > 0.35 * cw:
                bands.append((y0 + st, y0 + a + 1)); st = c
        bands = [bd for bd in bands if bd[1] - bd[0] > 0.4 * cw]
        if len(bands) < 2 or any(not any(bd[0] <= g["cy"] <= bd[1] for bd in bands) for g in groups):
            return None
        rows = []
        for r0, r1 in bands:
            roww = [w for w in inside if cx0 <= (w["box"][0] + w["box"][2]) / 2 <= cx1
                    and r0 <= (w["box"][1] + w["box"][3]) / 2 <= r1]
            spans = sorted(sp for w in roww for sp in self._hangul_spans(w, cw))
            # 한글이 아닌 글자(수식 조각)가 있는 자리: 낱말에서 한글 부분을 뺀 나머지
            others = []
            for w in roww:
                rest = HANGUL_RUN.sub(" ", w["val"]).strip()
                if not rest:
                    continue
                x = w["box"][0]
                for h0, h1, *_ in sorted(self._hangul_spans(w, cw)) + [(w["box"][2], w["box"][2])]:
                    if h0 - x > 1:
                        others.append((x, h0))
                    x = max(x, h1)
            maths, x = [], cx0
            for s0, s1, *_ in spans + [(cx1, cx1)]:
                # 한글 사이 빈칸은 수식이 아님: 한글 아닌 글자가 실제로 있는 틈만 수식 조각으로
                if s0 - x > 0.3 * cw and any(min(o1, s0) - max(o0, x) > 2 for o0, o1 in others):
                    t = _ink_box(gray, [x, r0 - 2, s0, r1 + 2])
                    if t and t[2] - t[0] > 0.2 * cw:
                        maths.append([float(v) for v in t])
                x = max(x, s1)
            rows.append({"band": (r0, r1), "maths": maths})
        left = _ink_box(gray, [b[0], b[1], cx0 - 1, b[3]])
        if not left:
            return None
        return {"box": [b[0], b[1], max(b[2], cx1), b[3]], "left": [float(v) for v in left], "rows": rows,
                "cond": [cx0, y0, cx1, y1]}

    def _join_cases(self, img, comp, items, cw):
        """_split_cases 로 나눈 조각을 읽어 cases 수식 하나로 합친다. 줄 수가 안 맞으면 None"""
        boxes = [comp["left"]] + [m for r in comp["rows"] for m in r["maths"]]
        outs = [clean_latex(x) for x in self.mfr([img.crop(tuple(int(v) for v in bx)) for bx in boxes])]
        left = outs[0]
        m = re.search(r"\\begin\{cases\}(.*)\\end\{cases\}", left, re.S)
        if not m:
            return None
        vals = [re.sub(r"\s*&[\s{}]*$", "", v).strip() for v in re.split(r"\\\\", m.group(1)) if v.strip(" {}&")]
        if len(vals) != len(comp["rows"]):
            return None
        c = comp["cond"]; k = 1; lines = []
        for val, row in zip(vals, comp["rows"]):
            r0, r1 = row["band"]
            parts = [(bx[0], bx[2], "math", outs[k + i]) for i, bx in enumerate(row["maths"])]
            k += len(row["maths"])
            parts += [(it["box"][0], it["box"][2], "text", str(it["val"])) for it in items
                      if it["kind"] == "text" and c[0] - 2 <= (it["box"][0] + it["box"][2]) / 2 <= c[2] + cw
                      and r0 <= (it["box"][1] + it["box"][3]) / 2 <= r1]
            split = []
            for x0, x1, kind, v in parts:
                inner = sorted((a + e) / 2 for a, e, kd, _ in parts if kd == "math" and x0 < (a + e) / 2 < x1) \
                    if kind == "text" else []
                if not inner:
                    split.append((x0, x1, kind, v)); continue
                cuts = [0] + [round(len(v) * (c_ - x0) / (x1 - x0)) for c_ in inner] + [len(v)]
                xb = [x0] + inner + [x1]
                for i in range(len(cuts) - 1):
                    piece = v[cuts[i]:cuts[i + 1]].strip(" :.,·|;'")
                    if piece:
                        split.append((xb[i] + 0.01, xb[i + 1] - 0.01, "text", piece))
            parts = split
            segs, prev = [], None
            for x0, x1, kind, v in sorted(parts, key=lambda t: t[0]):
                v = v.strip()
                if kind == "math":  # 조각 끝에 묻어 나온 점 등 찌꺼기 제거
                    v = re.sub(r"^(?:\\cdot|[.~]|\\[,;:! ]|\s)+|(?:\\cdot|[.~]|\\[,;:! ]|\s)+$", "", v)
                else:
                    v = v.replace("\\", "").replace("{", "(").replace("}", ")")
                if not v:
                    continue
                if kind == "text" and prev and prev[0] == "text":
                    segs[-1] = ("text", segs[-1][1] + (" " if x0 - prev[1] > 0.25 * cw else "") + v)
                else:
                    segs.append((kind, v))
                prev = (kind, x1)
            if self.spacer is not None:
                try:
                    from spacing import respace_paragraph
                    segs = respace_paragraph(self.spacer, segs)
                except Exception:  # noqa: BLE001
                    pass
            segs = [(k, v.rstrip() if k == "text" and i + 1 < len(segs) and segs[i + 1][1].startswith(")") else v)
                    for i, (k, v) in enumerate(segs)]
            cond = " ".join(v if k == "math" else "\\text{" + v + "}" for k, v in segs if v)
            lines.append(val + " & " + cond.strip())
        return left[:m.start()] + "\\begin{cases} " + " \\\\ ".join(lines) + " \\end{cases}" + left[m.end():]

    def _marks(self, img, lh, ws=()):
        import marks
        g = np.asarray(img.convert("L"))
        rec = lambda b: self._rec_one(img, b)  # noqa: E731
        try:
            items = [{"box": b, "kind": "text", "val": ch} for b, ch in marks.keep_in_order(marks.find_circles(g, lh))]
            items += [{"box": b, "kind": "math", "val": "\\boxed{\\text{(%s)}}" % ch}
                      for b, ch in marks.find_boxes(g, lh, rec)]
        except Exception:  # noqa: BLE001  찾지 못해도 나머지는 진행
            return []
        # <보기> 문제: 보기 ①~⑤ 의 값(ㄱ, ㄴ, ㄷ)을 모양으로 읽음
        ch = [(it["box"], it["val"]) for it in items if it["val"] in CHOICE_MARKS]
        if re.search(r"보\s*기", "".join(w["val"] for w in ws)):
            try:
                if ch:
                    items += [{"box": b, "kind": "text", "val": v} for b, v in marks.read_jamo_choices(g, ch, lh)]
                top = min(o["box"][1] for o in ws)
                for w in ws:  # 보기 안의 줄머리 ㄱ. ㄴ. ㄷ. (첫 줄의 문제 번호 '7.' 은 제외)
                    if not JAMO_HEAD.match(w["val"]) or not _leftmost(w, ws) or w["box"][1] < top + 0.5 * lh:
                        continue
                    r = marks.read_jamo_label(g, w["box"], lh)
                    if r:
                        items.append({"box": r[0], "kind": "text", "val": r[1]})
            except Exception:  # noqa: BLE001
                pass
        return items

    # ------------------------------------------------------------ 전체
    def __call__(self, img: Image.Image, figures: bool = True, letters=None):
        """letters: (굵게, 기울임) 이면 지문 속 대문자(점 이름 등)를 모두 수식으로, 그 글꼴로 통일. None 이면 그대로"""
        img = img.convert("RGB")
        src = img
        s = max(1.0, self.scale_to / img.width)
        if s > 1:
            img = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
        t0 = time.time()
        ws = self._words(img)
        # 그림·그래프·표: 원본에서 잘라 그림으로 넣고, 그 자리는 하얗게 지워 글자·수식 인식에서 뺀다
        fig_items = []
        if figures and self.figures is not None:
            from figures import crop_figure, ink_box, trim_text
            try:
                hs0 = sorted(w["box"][3] - w["box"][1] for w in ws if HANGUL_RUN.search(w["val"]))
                lh0 = hs0[len(hs0) // 2] if hs0 else 30
                figs = self.figures(img)
                circ = []
                if figs:  # 선지 번호 ①~⑤ (OCR 은 동그라미 숫자를 못 읽는 일이 많음): 그림 상자가 선지 줄을 품으면 잘라 냄
                    import marks
                    try:
                        circ = [{"box": b, "val": ch} for b, ch in marks.find_circles(np.asarray(img.convert("L")), lh0)
                                if ch in CHOICE_MARKS]
                    except Exception:  # noqa: BLE001
                        circ = []
                figs = trim_text(figs, ws + circ, lh0)
                figs = [dict(f, box=ink_box(img, f["box"])) for f in figs]  # 지우는 곳도 실제 그림까지만
            except Exception:  # noqa: BLE001  그림 찾기가 실패해도 글자·수식은 읽음
                figs = []
            if figs:
                img = img.copy(); d = ImageDraw.Draw(img)
                for f in figs:
                    b = f["box"]
                    d.rectangle([b[0] - 2, b[1] - 2, b[2] + 2, b[3] + 2], fill="white")
                    pic = crop_figure(src, [v / s for v in b])
                    fig_items.append({"box": b, "kind": "image", "val": Figure(pic, f["kind"], s)})
                inside = lambda w: any(f["box"][0] <= (w["box"][0] + w["box"][2]) / 2 <= f["box"][2]  # noqa: E731
                                       and f["box"][1] <= (w["box"][1] + w["box"][3]) / 2 <= f["box"][3] for f in figs)
                ws = [w for w in ws if not inside(w)]
        hs = sorted(w["box"][3] - w["box"][1] for w in ws if HANGUL_RUN.search(w["val"]))
        lh = hs[len(hs) // 2] if hs else 30
        cws = sorted((w["box"][2] - w["box"][0]) / len(w["val"]) for w in ws
                     if HANGUL_RUN.fullmatch(w["val"]) and len(w["val"]) >= 2)
        cw = cws[len(cws) // 2] if cws else 0.75 * lh
        self.last_em = cw / s if cws else None  # 원본 그림 기준 한글 한 글자 폭 (PDF 변환에서 글자 크기 추정)
        for f in fig_items:  # 그림 크기를 본문 글자 크기에 맞추려고 원본 기준 글자 폭(1em)을 기록
            f["val"].em = cw / s

        # 원문자(㉠, ㉮)와 네모 칸 (가): 찾아서 기록하고 가림
        mark_items = self._marks(img, lh, ws)
        # 보기 번호 ①~⑤ 는 수식 검출 그림에서는 남겨 둔다: 지우면 빈칸으로 띄엄띄엄 늘어선 보기 줄 전체를
        # 수식 검출이 표(array) 하나로 잡아 버림. 글자 OCR 그림에서만 가린다.
        choice_items = [it for it in mark_items if it["val"] in CHOICE_MARKS]
        if mark_items:
            img = img.copy(); d = ImageDraw.Draw(img)
            for it in mark_items:
                if it["val"] not in CHOICE_MARKS:
                    d.rectangle(it["box"], fill="white")
            ws = [w for w in ws if not any(_inter(w["box"], it["box"]) > 0.5 * _area(w["box"]) for it in mark_items)]
        fboxes = _split_at_rules(self._formulas(img), np.asarray(img.convert("L")), lh)
        if mark_items:
            # 수식 박스가 네모 칸 (가)·원문자를 품으면 그 자리에서 나눔. 안 나누면 "3 × [빈칸] ……" 이 수식 하나가 되고
            # 네모 칸이 그 뒤에 붙어 순서가 바뀜. 여러 줄 수식(cases 등)은 보기 번호만 나눔
            gray = np.asarray(img.convert("L"))
            cut = []
            for b in fboxes:
                marks_in = mark_items if b[3] - b[1] <= 2.2 * lh else choice_items
                parts = _cut_marks(b, marks_in)
                if len(parts) == 1 and parts[0] == list(b):  # 동그라미를 품지 않은 박스는 그대로 (여백도 그대로)
                    cut.append(b)
                else:
                    cut += [t for t in (_ink_box(gray, p) for p in parts) if t]
            fboxes = cut

        boxes = []
        korean = []  # 한글 낱말 자리에서 나눈 수식 박스 조각 중 실은 한글 글자인 것 (첫 OCR 이 놓친 글자)
        comps = []  # 조건 칸에 한글이 있는 여러 줄 수식: 줄별로 나눠 읽고 나중에 합침
        gray0 = np.asarray(img.convert("L"))
        for b in fboxes:
            h = b[3] - b[1]
            if h > 2.2 * lh:  # 여러 줄짜리 수식(cases, 큰 시그마 등)은 그대로
                try:
                    comp = self._split_cases(b, ws, cw, lh, gray0)
                except Exception:  # noqa: BLE001
                    comp = None
                if comp:
                    comps.append(comp)
                else:
                    boxes += self._split_tall_at_hangul(b, ws, cw, gray0)
                continue
            spans = sorted(sp for w in ws for sp in self._hangul_spans(w, cw)
                           if b[0] <= (sp[0] + sp[1]) / 2 <= b[2] and b[1] <= (sp[2] + sp[3]) / 2 <= b[3])
            x = b[0]
            for s0, s1, *_ in spans + [(b[2], b[2])]:
                if s0 - x > 0.3 * h:
                    piece = [x, b[1], s0, b[3]]
                    t = self._korean_piece(img, piece) if spans else None
                    if t:
                        korean.append((piece, t))
                    else:
                        boxes.append(piece)
                x = max(x, s1)
        self._gray = np.asarray(img.convert("L"))
        self._trimmed = list(korean)  # 수식 박스 끝에서 잘라 낸 한글 글자 (자리, 글자)
        boxes = [self._trim_tall(img, self._trim_edges(img, b, cw), cw, ws) for b in boxes]
        boxes = [b for b in boxes if b[2] - b[0] > 4]
        for comp in comps:
            for row in comp["rows"]:
                row["maths"] = [t for t in (self._trim_edges(img, m, cw) for m in row["maths"]) if t[2] - t[0] > 4]
        comp_boxes = [bx for comp in comps for bx in [comp["left"]] + [m for r in comp["rows"] for m in r["maths"]]]
        t1 = time.time()

        masked = img.copy(); d = ImageDraw.Draw(masked)
        for b in boxes + comp_boxes + [it["box"] for it in choice_items]:
            d.rectangle(b, fill="white")
        items = [{"box": w["box"], "kind": "text", "val": w["val"]} for w in self._words(masked, text_pass=True)]
        # 수식 검출이 놓친 근호 수식('9√77' = 9√7/7 분수를 글자로 읽음): 그 자리를 수식 인식으로 다시 읽음
        # 수식 검출이 놓친 세로 분수(5/4 를 '15|4' 처럼 두 줄을 한 단어로 읽음): 글자 줄보다 훨씬 키 큰 숫자 단어도 다시 읽음
        for it in [it for it in items if not HANGUL_RUN.search(it["val"]) and (
                _MISSED_ROOT.search(it["val"]) or (it["box"][3] - it["box"][1] >= 1.3 * lh
                                                   and re.fullmatch(r"[-0-9a-zA-Z|/+.]{2,}", it["val"]) and re.search(r"\d", it["val"])))]:
            t = list(it["box"]); h = t[3] - t[1]
            items.remove(it)
            for u in [u for u in items if re.fullmatch(r"[0-9a-z]{1,3}", u["val"])  # 바로 아래 분모
                      and t[0] <= (u["box"][0] + u["box"][2]) / 2 <= t[2] and abs(u["box"][1] - t[3]) < 0.5 * h]:
                t = [min(t[0], u["box"][0]), t[1], max(t[2], u["box"][2]), max(t[3], u["box"][3])]
                items.remove(u)
            py = 0.1 * h
            boxes.append([max(0, t[0] - 2), max(0, t[1] - py), min(img.width, t[2] + 2), min(img.height, t[3] + py)])
        # 잘라 낸 글자가 혼자 떨어져 있으면(줄 끝의 '이' 등) 글자 검출이 놓치는 일이 있다: 그 자리를 덮는 글자가 없으면 넣어 줌
        for g, ch in self._trimmed:
            gw = g[2] - g[0]
            def covers(it):
                t = it["box"]
                if min(t[3], g[3]) - max(t[1], g[1]) < 0.4 * min(t[3] - t[1], g[3] - g[1]):
                    return False
                if min(t[2], g[2]) - max(t[0], g[0]) > 0.3 * gw:
                    return True
                # 살짝 떨어져 있어도 같은 글자로 시작/끝나는 옆 글자 덩어리면 이미 읽힌 것
                v = str(it["val"]).strip()
                return bool(v) and ((v[0] == ch and 0 <= t[0] - g[0] < 1.2 * gw) or (v[-1] == ch and 0 <= g[2] - t[2] < 1.2 * gw))
            if not any(covers(it) for it in items):
                items.append({"box": g, "kind": "text", "val": ch})
        items += mark_items
        t2 = time.time()
        crops = [img.crop(tuple(int(v) for v in b)) for b in boxes]
        from formula_marks import split_circle_tail
        for b, crop, latex in zip(boxes, crops, self.mfr(crops) if crops else []):
            latex, tail = split_tail(clean_latex(latex))
            latex = _array_to_frac(latex, np.asarray(crop.convert("L")), cw)
            if _hallucinated(latex, b[2] - b[0], cw):
                # 수식 인식기가 지어낸 결과(같은 조각 반복, \newcommand·\put 같은 수식 밖 명령): 글자 인식으로 대신 읽음
                t, sc = self._rec_one(img, b)
                if t.strip() and sc > 0.6:
                    items.append({"box": list(b), "kind": "text", "val": t.strip()})
                continue
            if b[2] - b[0] < 1.2 * cw and re.search(r"\\frac\s*\{\s*\}|\\frac\s*\{[^{}]*\}\s*\{\s*\}", latex):
                continue  # 한 글자 폭 조각을 빈 분수로 읽음: 옆 한글 글자의 부스러기
            if not tail:  # "…… ⊙": 점선 뒤 동그라미 기호는 원문자 (원문자 검출이 놓친 경우)
                try:
                    latex, tail = split_circle_tail(latex, np.asarray(crop.convert("L")), lh)
                except Exception:  # noqa: BLE001
                    pass
            if not tail:  # 수식 끝의 " O" 는 '이/인' 인 경우가 많음: 끝부분을 글자 OCR 로 다시 읽어 봄
                mo = _TAIL_O.match(latex)
                if mo:
                    t, sc = self._rec_one(img, [max(b[0], b[2] - 1.3 * cw), b[1], b[2], b[3]])
                    if sc > 0.6 and t and HANGUL_RUN.fullmatch(t):
                        latex, tail = mo.group(1), t
            if tail and tail.strip() == "이":  # '이' 인지 '인' 인지 끝부분을 다시 읽어 봄
                t, sc = self._rec_one(img, [max(b[0], b[2] - 1.3 * cw), b[1], b[2], b[3]])
                if sc > 0.7 and t in ("인", "이고", "이며", "이다", "이면"):
                    tail = t
            segs = split_i(latex) if latex.strip() else []
            if tail:
                segs.append(("text", tail.strip() if not segs else tail))
            for i, (k, v) in enumerate(segs):  # 수식 오른쪽 끝 바로 뒤에 글자로 둔다 (x 를 조금씩 밀어 순서 유지)
                items.append({"box": [b[0] + 0.01 * i, b[1], b[2], b[3]], "kind": k, "val": v})
        for comp in comps:
            b = comp["box"]
            try:
                latex = self._join_cases(img, comp, items, cw)
            except Exception:  # noqa: BLE001
                latex = None
            # 조건 칸에서 글자로 읽힌 것은 수식 안으로 들어갔으므로(또는 통째로 다시 읽으므로) 뺀다
            items = [it for it in items if not (it["kind"] == "text"
                     and b[0] <= (it["box"][0] + it["box"][2]) / 2 <= b[2] + cw
                     and b[1] <= (it["box"][1] + it["box"][3]) / 2 <= b[3])]
            if latex is None:  # 줄 수가 안 맞는 등: 예전처럼 통째로 읽음
                latex = clean_latex(self.mfr([img.crop(tuple(int(v) for v in b))])[0])
            items.append({"box": b, "kind": "math", "val": latex})
        self.timing = (t1 - t0, t2 - t1, time.time() - t2)

        lines = [(cy, unify_choices(single_letters(o_after_math(zero_to_o(fix_choices(segs))))))
                 for cy, segs in merge_lines(items, with_y=True)]
        # 상자 테두리 같은 긴 가로줄 위·아래 줄은 한 문단으로 잇지 않음 ("(나) …" 와 상자 밖 다음 줄)
        lines += [(y, [("rule", "")]) for y in _rule_rows(self._gray, img.width)]
        lines = insert_figures(lines, fig_items)
        paras = fix_choice_runs(fix_condition_labels(to_paragraphs(lines)))
        paras = [_attach_scripts([(k, _fix_words(v) if k == "text" else v) for k, v in p]) for p in paras]
        if self.spacer is not None:
            from spacing import respace_paragraph
            paras = [respace_paragraph(self.spacer, p) for p in paras]
        if letters is not None:
            paras = [unify_letters(p, *letters) for p in paras]
        return [space_choices(_split_commas(p)) for p in paras]


_MISSED_ROOT = re.compile(r"√|\dV\d")
_LABELS = ["(가)", "(나)", "(다)", "(라)", "(마)"]
_LABEL_HEAD = re.compile(r"^\s*\(\s*([^()\s]{1,3})\s*\)\s*")


def fix_condition_labels(paras):
    """조건 (가)(나)(다) 줄머리: OCR 이 (나) 를 (4), (LH) 처럼 읽음. (가) 로 시작하는 문단이 있으면
    그 뒤 줄머리를 차례대로 (나), (다)… 로 맞춘다."""
    heads = [i for i, p in enumerate(paras) if p and p[0][0] == "text" and _LABEL_HEAD.match(p[0][1])]
    start = next((i for i in heads if _LABEL_HEAD.match(paras[i][0][1]).group(1) == "가"), None)
    if start is None:
        return paras
    k = 0
    for i in heads:
        if i < start:
            continue
        if k >= len(_LABELS):
            break
        m = _LABEL_HEAD.match(paras[i][0][1])
        if m.group(0).strip() != _LABELS[k]:
            if re.fullmatch(r"\d|[A-Za-z]{1,3}|[가-힣]", m.group(1)) is None:
                continue
            paras[i] = [("text", _LABELS[k] + " " + paras[i][0][1][m.end():])] + paras[i][1:]
        k += 1
    return paras


def fix_choice_runs(paras):
    """①~⑤ 가 든 문단이 이어진 곳(선지 줄들)마다 번호를 ① 부터 차례로 바로잡는다 (latex_fix.fix_choice_numbers)"""
    from latex_fix import fix_choice_numbers

    def is_choice(p):
        return all(k in ("text", "math") for k, _ in p) and any(
            k == "text" and any(c in v for c in CHOICE_MARKS) for k, v in p)

    out, i = [], 0
    while i < len(paras):
        if not is_choice(paras[i]):
            out.append(paras[i]); i += 1
            continue
        j = i
        while j < len(paras) and is_choice(paras[j]):
            j += 1
        out += fix_choice_numbers(paras[i:j])
        i = j
    return out


# ------------------------------------------------------------ 줄 묶기, 문단 만들기
class Figure:
    """문단 속 그림 한 개. img: 원본 해상도로 자른 그림, kind: image/table/chart, scale: 인식용 확대 배율"""

    def __init__(self, img: Image.Image, kind: str = "image", scale: float = 1.0):
        self.img, self.kind, self.scale = img, kind, scale
        self.em = None  # 원본 그림에서 본문 한글 한 글자 폭(px). 한글에 넣을 때 크기 계산에 씀

    def __repr__(self):
        return f"<그림 {self.kind} {self.img.width}x{self.img.height}>"


def _split_commas(segs):
    """'AB=2, AC=3' 을 수식 하나가 아니라 '수식, 수식' 으로 (latex_fix.split_commas)"""
    from latex_fix import split_commas
    out = []
    for k, v in segs:
        for k2, v2 in (split_commas(v) if k == "math" else [(k, v)]):
            if out and k2 == "text" and out[-1][0] == "text":  # 글자끼리만 붙임 (나란한 수식은 그대로 둠)
                out[-1] = ("text", out[-1][1] + v2)
            else:
                out.append((k2, v2))
    return out


def space_choices(segs):
    """선지 줄(① ② … 가 2개 이상)의 선지 사이를 넓게, 고르게 띄운다: 한 줄 5개면 빈칸 6개, 줄에 선지가 적을수록 넓게"""
    text = "".join(v for k, v in segs if k == "text")
    n = sum(c in text for c in CHOICE_MARKS)
    if n < 2:
        return segs
    gap = " " * {5: 6, 4: 9, 3: 12}.get(n, 16)
    out = [(k, re.sub(r"\s*([②③④⑤])", lambda m: gap + m.group(1), v) if k == "text" else v) for k, v in segs]
    if out and out[0][0] == "text":
        out[0] = ("text", out[0][1].lstrip())
    return out


def unify_letters(segs, bold: bool, italic: bool):
    """문단 속 알파벳 대문자 표기 통일: 글자로 읽힌 'ABC' 도 수식으로, 수식 속 mathbf/mathrm 등은 벗기고
    대문자 묶음에 정한 글꼴(굵게/기울임)을 입힘"""
    if any(k == "image" for k, _ in segs):
        return segs
    from latex_fix import letters_to_math, style_letters
    out = [(k, style_letters(v, bold, italic) if k == "math" else v) for k, v in letters_to_math(segs)]
    return _tidy(out) if out else out


def insert_figures(lines, fig_items):
    """(줄 가운데 y, segs) 목록에 그림을 한 줄씩 끼워 넣는다. 가운데가 그림 아랫변보다 위인 줄(그림 위의 글,
    그림 옆의 글)은 그림 앞에, 나머지는 뒤에. (윗변으로 비교하면 키 큰 분수 선지가 그림 앞으로 감) 결과: segs 목록"""
    out = []
    figs = sorted(fig_items, key=lambda f: f["box"][3])
    i = 0
    for cy, segs in sorted(lines, key=lambda t: t[0]):
        while i < len(figs) and cy >= figs[i]["box"][3] - 2:
            out.append([("image", figs[i]["val"])]); i += 1
        out.append(segs)
    out += [[("image", f["val"])] for f in figs[i:]]
    return out


def merge_lines(items, with_y=False):
    """위치로 줄을 묶고, 줄 안에서는 왼쪽→오른쪽. 띄운 간격이 크면 공백을 넣는다.
    with_y: (줄 가운데 y, segs) 로 돌려줌"""
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
            gap = it["box"][0] - prev["box"][2] if prev is not None else 0
            if prev is not None and (gap > 0.25 * h or prev["val"] in CHOICE_MARKS or (
                    # 한글 바로 뒤에 오는 수식 앞은 띄움 (OCR 이 놓치는 경우가 많음): "곡선 y=…", "점 A를"
                    it["kind"] == "math" and prev["kind"] == "text" and HANGUL_RUN.search(prev["val"][-1:]))):
                segs.append(("text", " "))
            segs.append((it["kind"], it["val"]))
            prev = it
        out.append(((ln["y0"] + ln["y1"]) / 2, _tidy(segs)) if with_y else _tidy(segs))
    return out


def _tidy(segs):
    """같은 종류끼리 붙이고, 줄 앞뒤 공백 정리"""
    out = []
    for k, v in segs:
        if out and k == "text" and out[-1][0] == "text":
            out[-1] = ("text", out[-1][1] + v)
        elif out and k == "math" and out[-1][0] == "math":  # 붙어 있는 수식은 한 개로
            out[-1] = ("math", out[-1][1] + " " + v)
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
        if segs[0][0] == "rule":
            prev_alone = True
            continue
        if any(k == "image" for k, _ in segs):  # 그림은 혼자 한 문단
            paras.append(list(segs)); prev_alone = True
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


def _md(k, v):
    return v if k == "text" else "[그림]" if k == "image" else f"${v}$"


def to_markdown(paras) -> str:
    """다른 프로그램용 글자: 수식은 $…$ 로 감쌈"""
    return "\n".join("".join(_md(k, v) for k, v in p) for p in paras)
