"""PDF 쪽 나누기: 쪽 그림 만들기, 단(왼쪽/오른쪽) 찾기, 머리말·꼬리말 빼기, 문제 번호 단위로 자르기.

시험지(수능·모의고사·학교 시험지)는 거의 모두 가운데 세로줄로 나뉜 2단이다. 그래서
1. 쪽 가운데 근처의 긴 세로줄 = 단 경계. 세로줄의 위·아래 끝이 본문 범위 (그 밖 = 머리말·쪽 번호).
   세로줄이 없으면 가운데 빈 띠(잉크 없는 세로 띠)를 찾고, 그것도 없으면 1단으로 본다.
2. 단마다 문제 번호("12.")를 단 왼쪽 끝에서 찾는다. PDF 글자 정보가 있으면 그것을, 없으면(스캔본) OCR 결과를 쓴다.
3. 단을 빈 줄로 덩어리(블록)로 나누고, 블록을 바로 위 문제 번호에 붙인다.
   "5지선다형", "단답형", "※ 확인 사항" 같은 안내 블록은 뺀다.
결과 좌표는 모두 쪽 그림의 픽셀 좌표.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

NUM_HEAD = re.compile(r"^\s*(\d{1,2})\s*[.．]")
# 안내 블록 (문제 내용이 아님): 이 글자로 시작하는 블록은 버림
DROP_HEAD = re.compile(r"^\s*(\d\s*지\s*선\s*다\s*형|단\s*답\s*형|이\s*문제지에\s*관한\s*저작권)")
# 시험 안내 상자 ("※ 확인 사항" 등): 문제에 붙이지 않고 원본 자리에 따로 둠
NOTICE_HEAD = re.compile(r"^\W{0,3}(확\s*인\s*사\s*항|※)")
PUA = re.compile(r"[-]")


@dataclass
class Block:
    box: list            # [x0, y0, x1, y1] 쪽 그림 픽셀
    text: str = ""       # 블록 안 글자 (PDF 글자 정보 또는 OCR)


@dataclass
class Problem:
    num: int | None      # 문제 번호 (None = 번호 없이 앞 문제에서 이어지는 내용)
    page: int            # 0부터
    col: int
    blocks: list = field(default_factory=list)
    num_box: list | None = None  # 쪽 그림에서 번호 "12." 가 차지한 곳 (인식 전에 지우고 번호는 글자로 넣음)
    kind: str = "problem"        # "notice" = 안내 상자 (blocks[0].text 에 줄마다 글)

    @property
    def box(self):
        bs = [b.box for b in self.blocks]
        return [min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs)]


# ---------------------------------------------------------------- 쪽 그림, 글자 정보
def open_pdf(path: str):
    import pypdfium2 as pdfium
    return pdfium.PdfDocument(path)


def render(doc, i: int, dpi: int) -> Image.Image:
    return doc[i].render(scale=dpi / 72).to_pil().convert("RGB")


def text_words(doc, i: int, dpi: int) -> list[dict]:
    """PDF 글자 정보 → 단어 [{"box": 픽셀 상자, "val": 글자}]. 수식 글꼴 글자(사설 영역 U+E000~)도 그대로 둠.
    글자 순서가 PDF 안에서 뒤섞인 경우가 많아(수식 글자, 번호의 점 등) 위치로 줄을 묶고 왼쪽→오른쪽으로 다시 늘어놓는다.
    글자 정보가 없으면 빈 목록."""
    page = doc[i]
    tp = page.get_textpage()
    n = tp.count_chars()
    if n <= 0:
        return []
    H = page.get_height()
    s = dpi / 72
    chars = []
    for k in range(n):
        ch = tp.get_text_range(k, 1)
        if not ch or ch.isspace() or ch in "\ufffe\ufeff\x00":
            continue
        l, b, r, t = tp.get_charbox(k)
        if r <= l or t <= b:
            continue
        chars.append(([l * s, (H - t) * s, r * s, (H - b) * s], ch))
    return group_words(chars)


def text_chars(doc, i: int, dpi: int) -> list:
    """PDF 글자 정보를 PDF 안의 차례 그대로: [(픽셀 상자 또는 None, 글자)]. 공백·줄바꿈도 넣음 (띄어쓰기 맞추기용)"""
    page = doc[i]
    tp = page.get_textpage()
    n = tp.count_chars()
    if n <= 0:
        return []
    H = page.get_height()
    s = dpi / 72
    out = []
    for k in range(n):
        ch = tp.get_text_range(k, 1)
        if not ch or ch in "\ufffe\ufeff\x00":
            continue
        try:
            l, b, r, t = tp.get_charbox(k)
        except Exception:  # noqa: BLE001  줄바꿈처럼 상자가 없는 글자
            l = r = 0
        out.append(([l * s, (H - t) * s, r * s, (H - b) * s] if r > l else None, ch))
    return out


def group_words(chars) -> list[dict]:
    """[(상자, 글자)] → 줄로 묶고 간격으로 나눈 단어 목록"""
    lines = []  # 글자 높이 큰 것부터 줄 기준을 잡음 (점·쉼표처럼 작은 글자가 줄을 만들지 않게)
    for box, ch in sorted(chars, key=lambda c: -(c[0][3] - c[0][1])):
        h = box[3] - box[1]
        cy = (box[1] + box[3]) / 2
        for ln in lines:
            if ln["y0"] - 0.15 * ln["h"] <= cy <= ln["y1"] + 0.15 * ln["h"] and h <= 1.6 * ln["h"]:
                ln["cs"].append((box, ch))
                break
        else:
            lines.append({"y0": box[1], "y1": box[3], "h": h, "cs": [(box, ch)]})
    words = []
    for ln in lines:
        cur = None
        h = ln["h"]
        for box, ch in sorted(ln["cs"], key=lambda c: c[0][0]):
            if cur is not None and box[0] - cur["box"][2] < 0.3 * h:
                cb = cur["box"]
                cur["val"] += ch
                cur["box"] = [min(cb[0], box[0]), min(cb[1], box[1]), max(cb[2], box[2]), max(cb[3], box[3])]
                continue
            cur = {"box": list(box), "val": ch}
            words.append(cur)
    words.sort(key=lambda w: (w["box"][1], w["box"][0]))
    return words


def has_text_layer(words: list[dict]) -> bool:
    """본문 글자 정보가 쓸 만큼 있는지 (한글 글자 수로 판단. 머리말만 있는 스캔본은 False)"""
    return sum(len(re.findall(r"[가-힣]", w["val"])) for w in words) >= 30


# ---------------------------------------------------------------- 단 찾기
def _longest_run(col: np.ndarray):
    d = np.diff(np.concatenate([[0], col.astype(np.int8), [0]]))
    s, e = np.where(d == 1)[0], np.where(d == -1)[0]
    if not len(s):
        return 0, 0, 0
    k = int(np.argmax(e - s))
    return int(e[k] - s[k]), int(s[k]), int(e[k])


def find_columns(ink: np.ndarray):
    """ink: 잉크(어두운 점) bool 배열 → (단 목록 [(x0, x1)], 본문 위, 본문 아래)"""
    H, W = ink.shape
    best = (0, 0, 0, 0)
    for x in range(int(W * 0.35), int(W * 0.65)):
        L, y0, y1 = _longest_run(ink[:, x])
        if L > best[0]:
            best = (L, x, y0, y1)
    L, x, y0, y1 = best
    if L > 0.4 * H:
        # 선 두께만큼 비켜 감
        xl, xr = x, x
        while xl > 0 and ink[y0:y1, xl - 1].mean() > 0.8:
            xl -= 1
        while xr < W - 1 and ink[y0:y1, xr + 1].mean() > 0.8:
            xr += 1
        return [(0, xl - 1), (xr + 2, W)], y0, y1
    # 세로줄 없음: 본문 범위 = 잉크 범위, 가운데 빈 띠가 있으면 2단
    rows = np.nonzero(ink.any(axis=1))[0]
    if not len(rows):
        return [], 0, 0
    top, bot = int(rows[0]), int(rows[-1]) + 1
    colink = ink[top:bot].mean(axis=0)
    mid = colink[int(W * 0.4):int(W * 0.6)]
    empty = mid < 0.002
    if empty.any():
        L, s, e = _longest_run(empty)
        if L > 0.01 * W:
            gx = int(W * 0.4) + (s + e) // 2
            # 한쪽이 거의 비어 있으면 1단
            if colink[:gx].sum() > 0.1 * colink.sum() and colink[gx:].sum() > 0.1 * colink.sum():
                return [(0, gx), (gx, W)], top, bot
    return [(0, W)], top, bot


def _blocks(ink: np.ndarray, x0: int, x1: int, y0: int, y1: int, gap: int):
    """단 안을 gap 이상 빈 줄로 나눈 블록 상자 목록 (잉크 범위로 줄임)"""
    sub = ink[y0:y1, x0:x1]
    rows = sub.any(axis=1)
    out, start, blank = [], None, 0
    for y, r in enumerate(rows.tolist() + [False] * (gap + 1)):
        if r:
            if start is None:
                start = y
            blank = 0
            last = y
        elif start is not None:
            blank += 1
            if blank >= gap:
                cols = np.nonzero(sub[start:last + 1].any(axis=0))[0]
                out.append([x0 + int(cols[0]), y0 + start, x0 + int(cols[-1]) + 1, y0 + last + 1])
                start, blank = None, 0
    return out


# ---------------------------------------------------------------- 문제 나누기
def _num_starts(words, x0, x1, y0, y1, lh):
    """단 왼쪽 끝에 있는 문제 번호 단어 → [(y, 번호, 단어 상자)]"""
    cand = []
    for w in words:
        b = w["box"]
        if not (x0 - lh <= b[0] < x1 and y0 <= (b[1] + b[3]) / 2 < y1):
            continue
        v = w["val"]
        if re.fullmatch(r"\d{1,2}", v):  # "1" 과 "." 사이가 조금 벌어진 경우: 바로 오른쪽 단어를 이어 봄
            h = b[3] - b[1]
            nxt = [o for o in words if 0 <= o["box"][0] - b[2] < 0.6 * h and o["box"][1] < b[3] and o["box"][3] > b[1] + 0.4 * h]
            if nxt:
                v += min(nxt, key=lambda o: o["box"][0])["val"]
        m = NUM_HEAD.match(v)
        if m:
            cand.append((b, int(m.group(1))))
    if not cand:
        return []
    left = min(b[0] for b, _ in cand)
    # 번호는 단 왼쪽 끝(가장 왼쪽 번호 근처)에 있음. 본문 속 "2." 같은 숫자는 안쪽에 있음
    cand = [(b, n) for b, n in cand if b[0] <= left + 1.5 * lh]
    # 같은 줄에서 왼쪽에 다른 글자가 있으면 줄 첫 단어가 아님
    out = []
    for b, n in cand:
        cy = (b[1] + b[3]) / 2
        if any(o["box"][2] <= b[0] and o["box"][0] >= x0 - lh and o["box"][1] < cy < o["box"][3]
               and o["val"].strip() for o in words):
            continue
        out.append((b[1], n, b))
    return sorted(out)


def _lines(ink, b, lh):
    """블록 안 글줄: [(y0, y1, 왼쪽 x)] (가로 잉크 투영으로 나눔)"""
    x0, y0, x1, y1 = b
    rows = ink[y0:y1, x0:x1].any(axis=1)
    out, start = [], None
    for y, r in enumerate(rows.tolist() + [False]):
        if r and start is None:
            start = y
        elif not r and start is not None:
            if y - start >= 0.3 * lh:
                cols = np.nonzero(ink[y0 + start:y0 + y, x0:x1].any(axis=0))[0]
                out.append((y0 + start, y0 + y, x0 + int(cols[0])))
            start = None
    return out


def _ocr_starts(img, ink, blocks, lh, rec, known):
    """단 왼쪽 끝에서 시작하는 글줄의 앞부분을 글자 인식으로 읽어 문제 번호를 찾는다.
    rec(그림) → (글자, 점수). known: 이미 찾은 번호의 y (근처는 건너뜀)"""
    lines = [ln for b in blocks for ln in _lines(ink, b, lh)]
    if not lines:
        return []
    # 본문 왼쪽 끝 = 가장 많은 글줄이 시작하는 x. 문제 번호는 그 자리이거나 그보다 왼쪽(내어쓰기)에 있다
    xs_all = sorted(ln[2] for ln in lines)
    left = max(xs_all, key=lambda x: (sum(abs(x - o) < 0.5 * lh for o in xs_all), -x))
    out = []
    for y0, y1, xs in lines:
        if True:
            if xs > left + 0.8 * lh or y1 - y0 > 4 * lh or any(abs(y - y0) < lh for y in known):
                continue
            crop = img.crop((max(0, xs - 4), max(0, y0 - 4), xs + int(3.2 * lh), y1 + 4))
            t, sc = rec(crop)
            m = NUM_HEAD.match(t.replace(" ", ""))
            if m and sc > 0.5:
                out.append((y0, int(m.group(1)), [xs, y0, xs + lh, y1]))
    return out


def _number_box(ink, nb, lh):
    """번호 단어 상자(대략) 근처의 잉크로 "12." 의 실제 범위를 찾는다: 왼쪽부터 잉크 덩어리를 차례로 보다가
    아래쪽에만 있는 작은 덩어리(마침표)를 만나면 거기까지."""
    x0 = int(nb[0]) - 2
    y0, y1 = int(nb[1]), int(nb[3])
    band = ink[max(0, y0 - 2):y1 + 2, max(0, x0):x0 + int(3 * lh)]
    if not band.size:
        return None
    cols = band.any(axis=0)
    runs, start = [], None
    for x, c in enumerate(cols.tolist() + [False]):
        if c and start is None:
            start = x
        elif not c and start is not None:
            runs.append((start, x))
            start = None
    h = band.shape[0]
    end = None
    for a, b in runs:
        ys = np.nonzero(band[:, a:b].any(axis=1))[0]
        if b - a < 0.45 * lh and len(ys) and ys.min() > 0.55 * h:  # 마침표
            end = b
            break
        if a > 2.2 * lh:
            break
    if end is None:
        return None
    return [max(0, x0), max(0, y0 - 2), max(0, x0) + end + 1, y1 + 2]


def _rec_text(img, b, lh, rec):
    """글자 정보가 없는 작은 블록(안내 상자 "5지선다형" 등인지 보려고)만 글자 인식"""
    if rec is None or b[3] - b[1] > 2.5 * lh or b[2] - b[0] > 14 * lh:
        return ""
    return rec(img.crop((max(0, b[0] - 3), max(0, b[1] - 3), b[2] + 3, b[3] + 3)))[0]


def _block_text(words, box):
    ws = [w for w in words if box[0] <= (w["box"][0] + w["box"][2]) / 2 <= box[2]
          and box[1] <= (w["box"][1] + w["box"][3]) / 2 <= box[3]]
    ws.sort(key=lambda w: (round(w["box"][1] / 10), w["box"][0]))
    return " ".join(w["val"] for w in ws)


def _framed(ink, b, lh):
    """블록이 네모 테두리 안에 있나 (왼쪽·오른쪽 끝 세로줄이 거의 끝까지)"""
    x0, y0, x1, y1 = b
    if y1 - y0 < 2 * lh:
        return False
    h = y1 - y0
    k = max(2, int(0.15 * lh))
    left = ink[y0:y1, x0:x0 + k].any(axis=1).mean()
    right = ink[y0:y1, x1 - k:x1].any(axis=1).mean()
    return left > 0.9 and right > 0.9 and h > 0


def _inner(ink, b, lh):
    """테두리 안쪽 (테두리 선을 뺀 범위)"""
    m = max(3, int(0.35 * lh))
    return [b[0] + m, b[1] + m, b[2] - m, b[3] - m]


def text_lines(words, box):
    """블록 안 PDF 글자 정보를 줄별 글로 (위→아래, 줄 안에서 왼쪽→오른쪽)"""
    ws = [w for w in words if box[0] <= (w["box"][0] + w["box"][2]) / 2 <= box[2]
          and box[1] <= (w["box"][1] + w["box"][3]) / 2 <= box[3] and not PUA.search(w["val"])]
    ws.sort(key=lambda w: (w["box"][1] + w["box"][3]) / 2)
    lines = []
    for w in ws:
        cy = (w["box"][1] + w["box"][3]) / 2
        if lines and abs(cy - lines[-1][0]) < 0.5 * (w["box"][3] - w["box"][1]):
            lines[-1][1].append(w)
        else:
            lines.append([cy, [w]])
    return [" ".join(x["val"] for x in sorted(l, key=lambda w: w["box"][0])) for _, l in lines]


def notice_lines(img, ink, b, lh, words, rec):
    """안내 상자의 글을 줄별로: PDF 글자 정보가 있으면 그것, 없으면 줄마다 글자 인식"""
    inner = _inner(ink, b, lh) if _framed(ink, b, lh) else b
    if words:
        out = text_lines(words, inner)
        if out:
            return out
    if rec is None:
        return []
    return [t for t in (rec(img.crop((max(0, inner[0] - 2), l0 - 2, inner[2] + 2, l1 + 2)))[0].strip()
                        for l0, l1, _ in _lines(ink, inner, lh)) if t]


def _is_notice(img, ink, b, lh, words, rec, text):
    if NOTICE_HEAD.match(text) or re.match(r"^\W{0,3}확\s*인\s*사\s*항", text.replace("*", "")):
        return True
    if text and not text.lstrip().startswith(("확", "※", "*")) and "사항" not in text[:12]:
        return False
    if not _framed(ink, b, lh) or rec is None:
        return False
    ls = _lines(ink, _inner(ink, b, lh), lh)
    if not ls:
        return False
    l0, l1, _ = ls[0]
    inner = _inner(ink, b, lh)
    head = rec(img.crop((max(0, inner[0] - 2), l0 - 2, inner[2] + 2, l1 + 2)))[0]
    return bool(re.search(r"확\s*인\s*사\s*항", head))


def split_page(img: Image.Image, words: list[dict], page: int, dpi: int, rec=None):
    """쪽 그림 + 단어(PDF 글자 정보 또는 OCR) → 문제 목록 (단 순서, 위→아래).
    번호 없는 첫 블록은 num=None (앞 쪽·앞 단의 문제에서 이어지는 내용)."""
    gray = np.asarray(img.convert("L"))
    ink = gray < 160
    cols, top, bot = find_columns(ink)
    lh = dpi * 10 / 72  # 10pt 글자 높이 (픽셀)
    hs = sorted(w["box"][3] - w["box"][1] for w in words if re.search(r"[가-힣]", w["val"]))
    if hs:
        lh = hs[len(hs) // 2]
    gap = max(3, int(0.9 * lh))
    probs = []
    for ci, (x0, x1) in enumerate(cols):
        # 단 경계 세로줄 옆 여백, 쪽 가장자리 쪽번호·테두리선 등은 블록 잉크 범위로 걸러짐
        starts = _num_starts(words, x0, x1, top, bot, lh)
        blocks = _blocks(ink, x0, x1, top, bot, gap)
        # 쪽 전체를 덮는 테두리·아주 작은 점은 버림
        blocks = [b for b in blocks if (b[2] - b[0]) * (b[3] - b[1]) > 0.5 * lh * lh and b[3] - b[1] < 0.98 * (bot - top)]
        if rec is not None:  # PDF 글자 정보가 놓친 번호(글자 순서가 뒤섞인 경우), 스캔본: 줄 앞부분을 글자 인식
            starts = sorted(starts + _ocr_starts(img, ink, blocks, lh, rec, [s[0] for s in starts]))
        cur = None
        si = 0
        for b in blocks:
            # 이 블록 안(또는 위)에서 시작하는 문제 번호
            while si < len(starts) and starts[si][0] < b[3] - 0.3 * lh:
                y, n, nb = starts[si]
                si += 1
                # 번호가 있는 글줄의 위 끝 (분수 등으로 번호보다 위로 솟은 줄)
                ly = next((l0 for l0, l1, _ in _lines(ink, b, lh) if l0 - 2 <= y < l1), y)
                if b[1] < ly - 0.5 * lh:
                    # 번호가 블록 중간에서 시작: 번호 위쪽은 앞 문제(또는 안내 블록)로 나눔
                    up = [b[0], b[1], b[2], int(ly - 1)]
                    t = _block_text(words, up) or _rec_text(img, up, lh, rec)
                    if not DROP_HEAD.match(t) and not (up[3] - up[1] < 0.4 * lh and not t):
                        if cur is None:
                            cur = Problem(None, page, ci)
                            probs.append(cur)
                        cur.blocks.append(Block(up, t))
                    b = [b[0], int(ly), b[2], b[3]]
                cur = Problem(n, page, ci, num_box=_number_box(ink, nb, lh))
                probs.append(cur)
            t = _block_text(words, b) or _rec_text(img, b, lh, rec)
            if DROP_HEAD.match(t) or (b[3] - b[1] < 0.4 * lh and not t):  # 안내 블록, 가로줄
                continue
            if _is_notice(img, ink, b, lh, words, rec, t):
                probs.append(Problem(None, page, ci, [Block(b, "\n".join(notice_lines(img, ink, b, lh, words, rec)))],
                                     kind="notice"))
                cur = None
                continue
            if cur is None:
                cur = Problem(None, page, ci)
                probs.append(cur)
            cur.blocks.append(Block(b, t))
    probs = [p for p in probs if p.blocks]
    # 문제 번호 줄 바로 위에 떨어져 있던 작은 조각(분수의 분자, 위첨자 등)은 그 문제로 옮긴다
    for a, b in zip(probs, probs[1:]):
        if a.col != b.col or b.num is None or a.kind != "problem":
            continue
        while a.blocks:
            t = a.blocks[-1].box
            if t[3] - t[1] < 1.3 * lh and 0 <= b.blocks[0].box[1] - t[3] < 1.3 * lh:
                b.blocks.insert(0, a.blocks.pop())
            else:
                break
    # 번호 없는 맨 앞 조각 중 글자 없는 얇은 것(머리말 아래 가로줄·제목 띠)은 버림
    probs = [p for p in probs if p.blocks and not (
        p.num is None and p.kind == "problem" and all(not bl.text.strip() and bl.box[3] - bl.box[1] < 1.5 * lh for bl in p.blocks))]
    return probs, {"cols": cols, "top": top, "bot": bot, "lh": lh}


def problem_image(img: Image.Image, prob: Problem, lh: float, pad: int = 6, erase_number: bool = True) -> Image.Image:
    """문제의 블록들을 위→아래로 이어 붙인 그림 (풀이용 큰 빈칸은 줄임).
    erase_number: 번호 "12." 를 지움 (번호는 따로 글자로 넣음: 수식 검출이 번호를 수식에 붙여 읽는 일을 막음)"""
    if erase_number and prob.num_box:
        from PIL import ImageDraw
        img = img.copy()
        ImageDraw.Draw(img).rectangle(prob.num_box, fill="white")
    bs = [b.box for b in prob.blocks]
    x0 = max(0, min(b[0] for b in bs) - pad)
    x1 = min(img.width, max(b[2] for b in bs) + pad)
    parts, prev = [], None
    for b in bs:
        y0 = max(0, b[1] - pad)
        y1 = min(img.height, b[3] + pad)
        if prev is not None and y0 - prev < 1.5 * lh:  # 가까운 블록은 원래 간격 그대로
            parts[-1] = (parts[-1][0], y1)
        else:
            parts.append((y0, y1))
        prev = y1
    gapw = int(lh)
    H = sum(e - s for s, e in parts) + gapw * (len(parts) - 1)
    out = Image.new("RGB", (x1 - x0, H), "white")
    y = 0
    for s, e in parts:
        out.paste(img.crop((x0, s, x1, e)), (0, y))
        y += e - s + gapw
    # 둘레에 흰 여백: 글자가 그림 가장자리에 붙어 있으면 글자 검출(OCR)이 줄을 통째로 놓치는 일이 있음
    from PIL import ImageOps
    return ImageOps.expand(out, border=max(pad, int(0.8 * lh)), fill="white")
