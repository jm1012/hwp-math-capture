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

from latex_fix import clean_latex, fix_choices, single_letters, split_tail, zero_to_o

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
    def __init__(self, mfd, mfr, ocr_det: str, ocr_rec: str, ocr_dict: str, scale_to: int = 1000):
        from rapidocr import RapidOCR
        from rapidocr.ch_ppocr_rec import TextRecInput
        self.mfd, self.mfr, self.scale_to = mfd, mfr, scale_to
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

    def _marks(self, img, lh, ws=()):
        import marks
        g = np.asarray(img.convert("L"))
        rec = lambda b: self._rec_one(img, b)  # noqa: E731
        try:
            items = [{"box": b, "kind": "text", "val": ch} for b, ch in marks.find_circles(g, lh)]
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
    def __call__(self, img: Image.Image):
        img = img.convert("RGB")
        s = max(1.0, self.scale_to / img.width)
        if s > 1:
            img = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
        t0 = time.time()
        ws = self._words(img)
        hs = sorted(w["box"][3] - w["box"][1] for w in ws if HANGUL_RUN.search(w["val"]))
        lh = hs[len(hs) // 2] if hs else 30
        cws = sorted((w["box"][2] - w["box"][0]) / len(w["val"]) for w in ws
                     if HANGUL_RUN.fullmatch(w["val"]) and len(w["val"]) >= 2)
        cw = cws[len(cws) // 2] if cws else 0.75 * lh

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
        fboxes = self._formulas(img)
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
        for b in boxes + [it["box"] for it in choice_items]:
            d.rectangle(b, fill="white")
        items = [{"box": w["box"], "kind": "text", "val": w["val"]} for w in self._words(masked, text_pass=True)] + mark_items
        t2 = time.time()
        crops = [img.crop(tuple(int(v) for v in b)) for b in boxes]
        from formula_marks import split_circle_tail
        for b, crop, latex in zip(boxes, crops, self.mfr(crops) if crops else []):
            latex, tail = split_tail(clean_latex(latex))
            if not tail:  # "…… ⊙": 점선 뒤 동그라미 기호는 원문자 (원문자 검출이 놓친 경우)
                try:
                    latex, tail = split_circle_tail(latex, np.asarray(crop.convert("L")), lh)
                except Exception:  # noqa: BLE001
                    pass
            if not latex.strip():
                if tail:
                    items.append({"box": b, "kind": "text", "val": tail.strip()})
                continue
            items.append({"box": b, "kind": "math", "val": latex})
            if tail:  # 수식 오른쪽 끝 바로 뒤에 글자로 둔다
                items.append({"box": [b[0] + 0.01, b[1], b[2], b[3]], "kind": "text", "val": tail})
        self.timing = (t1 - t0, t2 - t1, time.time() - t2)

        lines = [single_letters(zero_to_o(fix_choices(segs))) for segs in merge_lines(items)]
        paras = to_paragraphs(lines)
        if self.spacer is not None:
            from spacing import respace_paragraph
            paras = [respace_paragraph(self.spacer, p) for p in paras]
        return paras


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
            gap = it["box"][0] - prev["box"][2] if prev is not None else 0
            if prev is not None and (gap > 0.25 * h or prev["val"] in CHOICE_MARKS or (
                    # 한글 바로 뒤에 오는 수식 앞은 띄움 (OCR 이 놓치는 경우가 많음): "곡선 y=…", "점 A를"
                    it["kind"] == "math" and prev["kind"] == "text" and HANGUL_RUN.search(prev["val"][-1:]))):
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
