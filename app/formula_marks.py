"""수식 한 개 캡처(수식 모드)에서 네모 칸 (가)(나) 와 점선 뒤 원문자 ㉠㉡ 바로잡기.

수식 인식기(MFR)는
- 네모 칸 속 (가) 를 \\fbox{(7♯)}, \\fbox{(7\\})} 처럼 읽고 (한글을 모름)
- "…… ㉠" 의 원문자를 \\odot, \\bigcirc 로 읽는다.
지문 모드와 같은 방법(marks.py)으로 그림에서 네모 칸과 원문자를 찾아 바꿔 넣는다.
점선(\\cdots …) 뒤에 동그라미 비슷한 기호가 오면, 동그라미 검출이 실패해도 원문자로 보고 모양으로 읽는다.
"""
from __future__ import annotations

import re

import numpy as np
from PIL import Image

import marks

_BOX = re.compile(r"\\(?:fbox|boxed|framebox)\s*\{")
_SPACE = r"(?:\s|~|\\[,;:! ]|\\q?quad)"
_DOTS = r"(?:\\[cl]?dots|\\cdot|\\ldotp|\\cdotp|\.|·)"
_JUNK = (r"(?:\\(?:odot|bigodot|circ|bigcirc|ominus|oplus|otimes|copyright|circledcirc|Theta|theta|ocircle)"
         r"|\\textcircled\s*\{[^{}]*\}|\(\s*[^()]{1,4}\s*\))")
_TAIL = re.compile(rf"(?P<dots>(?:{_SPACE}*{_DOTS})+)?{_SPACE}*(?P<junk>(?:{_JUNK}{_SPACE}*)+)$")
_TRAIL_SPACE = re.compile(rf"{_SPACE}+$")


def _replace_boxes(latex: str, vals: list[str]) -> str:
    out, pos, k = [], 0, 0
    for m in _BOX.finditer(latex):
        if k >= len(vals) or m.start() < pos:
            break
        d, j = 1, m.end()
        while j < len(latex) and d:
            if latex[j] == "\\":  # \{ \} 는 괄호 짝 세기에서 뺌
                j += 2
                continue
            d += latex[j] == "{"; d -= latex[j] == "}"
            j += 1
        out.append(latex[pos:m.start()] + vals[k])
        pos, k = j, k + 1
    return "".join(out) + latex[pos:]


def _last_circle(g: np.ndarray, lh: float) -> str | None:
    """그림 오른쪽 끝의 동그라미 덩어리를 원문자 견본과 비교 (Hough 검출이 놓쳤을 때)"""
    import cv2
    bw = (g < 200).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(bw, connectivity=8)
    cands = [i for i in range(1, n) if st[i][3] >= 0.4 * lh and 0.75 < st[i][2] / max(1, st[i][3]) < 1.33]
    if not cands:
        return None
    i = max(cands, key=lambda i: st[i][0] + st[i][2])
    x, y, w, h, _a = st[i]
    m = max(w, h) // 2 + 1
    cx, cy = x + w // 2, y + h // 2
    crop = g[max(0, cy - m):cy + m + 1, max(0, cx - m):cx + m + 1]
    v = marks._glyph_vec(crop < 200)
    if v is None:
        return None
    score, ch = max((float(v @ t), c) for c, t in marks.templates() if c in marks.CIRCLED)
    return ch if score > 0.3 else None


def fix_formula_marks(reader, img: Image.Image, latex: str) -> tuple[str, str]:
    """reader: PassageReader. 결과 (LaTeX, 수식 뒤에 글자로 붙일 것)"""
    bare = _TRAIL_SPACE.sub("", re.sub(r"\\$", "", latex.rstrip()))
    if not _BOX.search(latex) and not _TAIL.search(bare):
        return latex, ""  # 네모 칸도 끝의 동그라미 기호도 없으면 그림 검사 생략 (OCR 이 1초쯤 걸림)
    img = img.convert("RGB")
    s = max(1.0, reader.scale_to / img.width)
    if s > 1:
        img = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
    ws = reader._words(img)
    hs = sorted(w["box"][3] - w["box"][1] for w in ws)
    lh = hs[len(hs) // 2] if hs else 0.7 * img.height
    items = reader._marks(img, lh)
    boxes = sorted((it for it in items if it["kind"] == "math"), key=lambda it: it["box"][0])
    circles = sorted((it for it in items if it["val"] in marks.CIRCLED), key=lambda it: it["box"][0])

    if boxes and _BOX.search(latex):
        latex = _replace_boxes(latex, [b["val"] for b in boxes])

    return split_circle_tail(latex, np.asarray(img.convert("L")), lh, circles[-1]["val"] if circles else None)


def split_circle_tail(latex: str, gray: np.ndarray, lh: float, known: str | None = None) -> tuple[str, str]:
    """수식 끝의 '점선 + 동그라미 기호' → 동그라미 기호를 떼어 원문자 글자로.
    점선(CDOTS)은 수식에 남긴다 (한글 문제에서도 점선은 수식 안에 씀). 결과 (LaTeX, 붙일 글자)"""
    latex = _TRAIL_SPACE.sub("", re.sub(r"\\$", "", latex.rstrip()))
    m = _TAIL.search(latex)
    if not m or not (m.group("dots") or known):
        return latex, ""
    ch = known or _last_circle(gray, lh)
    if not ch:
        return latex, ""
    return _TRAIL_SPACE.sub("", latex[:m.start("junk")]).strip(), " " + ch
