"""OCR 사전에 없는 표시 글자 찾기

- 원문자 ㉠㉡… / ㉮㉯…  : 동그라미를 찾고, 설치된 글꼴로 그린 원문자 견본과 모양을 비교
  (OCR 사전에 원문자가 없어 OCR 로는 읽을 수 없음)
- 네모 칸 속 (가)(나)…   : 작은 사각형을 찾고 안쪽을 읽어 수식 BOX{"(가)"} 로 만듦

둘 다 찾은 자리는 흰색으로 가린 뒤 나머지(수식 검출, OCR)를 진행한다.
"""
from __future__ import annotations

import os
import re

import numpy as np
from PIL import Image, ImageDraw, ImageFont

SYLL = "가나다라마바사아자차카타파하"
CIRCLED = [chr(0x3260 + i) for i in range(14)] + [chr(0x326E + i) for i in range(14)]  # ㉠..㉭, ㉮..㉻
DIGITS = [chr(0x2460 + i) for i in range(10)]  # ①..⑩ 는 OCR 이 직접 읽으므로 건드리지 않음
BOXED = re.compile(r"[(\[]?([가-하])[)\]]?")

FONT_DIRS = [os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Fonts"),
             os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows\Fonts"),
             "/usr/share/fonts/truetype/nanum", "/usr/share/fonts/opentype/noto"]
FONT_FILES = ["HCRBatang.ttf", "HCRDotum.ttf", "batang.ttc", "malgun.ttf", "gulim.ttc",
              "NanumMyeongjo.ttf", "NanumGothic.ttf", "NotoSerifCJK-Regular.ttc"]
N = 32
_templates = None


def _glyph_vec(a):
    """동그라미(정사각 영역) 속 글자만 남겨 글자 테두리에 맞춰 N×N 으로 키운 뒤 비교용 벡터로"""
    h, w = a.shape
    yy, xx = np.mgrid[:h, :w]
    a = a & (((xx + 0.5 - w / 2) / (w / 2)) ** 2 + ((yy + 0.5 - h / 2) / (h / 2)) ** 2 < 0.72 ** 2)
    ys, xs = np.nonzero(a)
    if len(xs) < 4 or np.ptp(xs) < 0.25 * w or np.ptp(ys) < 0.25 * h:  # 속이 빈 동그라미(알파벳 O 등)
        return None
    a = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    v = np.asarray(Image.fromarray(a.astype(np.uint8) * 255).resize((N, N), Image.BILINEAR), float) / 255
    v = np.concatenate([v.ravel(), [a.shape[1] / a.shape[0] * 2]])  # 가로세로 비율도 반영
    v = v - v.mean()
    return v / (np.linalg.norm(v) + 1e-6)


def _render(font, ch):
    im = Image.new("L", (160, 160), 255)
    ImageDraw.Draw(im).text((30, 20), ch, font=font, fill=0)
    a = np.asarray(im) < 128
    ys, xs = np.nonzero(a)
    return a[ys.min():ys.max() + 1, xs.min():xs.max() + 1] if len(xs) else None


def templates():
    """설치된 글꼴로 원문자 견본을 그린다 (글꼴마다 모양이 조금씩 달라서 여러 개)"""
    global _templates
    if _templates is None:
        _templates = []
        for d in FONT_DIRS:
            for f in FONT_FILES:
                path = os.path.join(d, f)
                if not os.path.exists(path):
                    continue
                try:
                    font = ImageFont.truetype(path, 80)
                except OSError:
                    continue
                missing = _render(font, "\U0010FFFD")
                for ch in CIRCLED + DIGITS:
                    a = _render(font, ch)
                    if a is None or (missing is not None and a.shape == missing.shape and (a == missing).all()):
                        continue
                    if abs(a.shape[0] - a.shape[1]) > 0.15 * a.shape[0]:  # 동그라미가 아닌 대체 글리프
                        continue
                    v = _glyph_vec(a)
                    if v is not None:
                        _templates.append((ch, v))
    return _templates


def _ring(g, x, y, r, th=200):
    t = np.linspace(0, 2 * np.pi, 72, endpoint=False)
    xs = np.clip((x + r * np.cos(t)).round().astype(int), 1, g.shape[1] - 2)
    ys = np.clip((y + r * np.sin(t)).round().astype(int), 1, g.shape[0] - 2)
    return float(np.mean([g[b - 1:b + 2, a - 1:a + 2].min() < th for a, b in zip(xs, ys)]))


def find_circles(g, lh):
    """g: 회색조 배열, lh: 글자 높이(px). 결과 [(box, '㉠'), …]"""
    import cv2
    T = templates()
    if not T:
        return []
    c = cv2.HoughCircles(cv2.GaussianBlur(g, (3, 3), 0), cv2.HOUGH_GRADIENT, dp=1,
                         minDist=max(8, int(0.8 * lh)), param1=120, param2=18,
                         minRadius=max(6, int(0.25 * lh)), maxRadius=max(10, int(0.8 * lh)))
    out = []
    if c is None:
        return out
    for x, y, r in np.round(c[0]).astype(int):
        # 중심과 반지름을 1px 단위로 맞춤 (둘레가 가장 잘 겹치는 곳)
        on, rr, x, y = max((_ring(g, x + dx, y + dy, k), k, x + dx, y + dy)
                           for k in range(r - 3, r + 4) for dx in (-1, 0, 1) for dy in (-1, 0, 1))
        if on < 0.85 or _ring(g, x, y, rr + 4) > 0.4 or rr > 0.48 * lh:
            continue
        if not _isolated(g, x, y, rr):  # 굵은 숫자 "5." 의 둥근 아랫부분처럼 바깥 획과 이어진 동그라미
            continue
        m = rr + 1
        crop = g[max(0, y - m):y + m + 1, max(0, x - m):x + m + 1]
        if crop.shape[0] != crop.shape[1]:
            continue
        v = _glyph_vec(crop < 200)
        if v is None:
            continue
        score, ch = max((float(v @ t), ch) for ch, t in T)
        if (ch in CIRCLED and score > 0.4) or (ch in CHOICES and score > 0.5):
            out.append(([int(x - m - 2), int(y - m - 2), int(x + m + 2), int(y + m + 2)], ch))
    return out


def keep_in_order(found):
    """원문자는 지문에 ㉠, ㉡, ㉢ … (또는 ㉮, ㉯ …) 차례로 나온다. 앞 글자 없이 뒤 글자만 나온 것은
    굵은 O·C 같은 알파벳을 원문자로 잘못 본 것이라 버린다 (예: 원점 O → ㉧, C → ㉡).
    found: [(box, ch), …]. ㉠(㉮)이 있어야 하고, 이어지는 차례에서 한 칸 건너뛴 것까지는 봐 줌."""
    out = []
    for series in (CIRCLED[:14], CIRCLED[14:]):
        have = {ch for _, ch in found if ch in series}
        n = 0  # 맨 앞부터 이어지는 글자 수
        while n < len(series) and series[n] in have:
            n += 1
        ok = set(series[:n + 2]) if n else set()
        out += [(b, ch) for b, ch in found if ch in series and ch in ok]
    return out + [(b, ch) for b, ch in found if ch not in CIRCLED]


CHOICES = DIGITS[:5]  # 보기 번호 ①~⑤: OCR 이 3, 4 로 읽거나 통째로 놓치는 일이 많아 모양으로 직접 찾음


def _isolated(g, x, y, r, th=200):
    """동그라미 둘레의 검은 획이 동그라미 밖으로 뻗어 나가지 않는지 (원문자는 둘레가 따로 떨어진 한 덩어리)"""
    import cv2
    m = 2 * r + 4
    y0, x0 = max(0, y - m), max(0, x - m)
    win = (g[y0:y + m + 1, x0:x + m + 1] < th).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(win, connectivity=8)
    t = np.linspace(0, 2 * np.pi, 72, endpoint=False)
    xs = np.clip((x - x0 + r * np.cos(t)).round().astype(int), 0, win.shape[1] - 1)
    ys = np.clip((y - y0 + r * np.sin(t)).round().astype(int), 0, win.shape[0] - 1)
    ids = set()
    for a, b in zip(xs, ys):
        patch = lab[max(0, b - 1):b + 2, max(0, a - 1):a + 2]
        ids.update(int(v) for v in patch.ravel() if v)
    lim = r + 2 + 0.15 * r
    for i in ids:
        bx, by, bw, bh, _ = stats[i]
        if (x - x0 - bx > lim or bx + bw - (x - x0) > lim or y - y0 - by > lim or by + bh - (y - y0) > lim):
            return False
    return True


def find_boxes(g, lh, rec):
    """작은 네모 칸 속 (가)(나)… → [(box, '가'), …]"""
    import cv2
    bw = (g < 150).astype(np.uint8)
    cnts, _ = cv2.findContours(bw, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for cnt in cnts:
        x, y, w, h = cv2.boundingRect(cnt)
        if not (0.5 * lh <= h <= 2 * lh and 0.8 * lh <= w <= 6 * lh):
            continue
        if any(x >= b[0] - 2 and y >= b[1] - 2 and x + w <= b[2] + 2 and y + h <= b[3] + 2 for b, _ in out):
            continue
        # 네 변이 거의 다 검은 선인지
        e = 2
        sides = [bw[y:y + e + 1, x:x + w].max(0), bw[y + h - 1 - e:y + h, x:x + w].max(0),
                 bw[y:y + h, x:x + e + 1].max(1), bw[y:y + h, x + w - 1 - e:x + w].max(1)]
        if min(s.mean() for s in sides) < 0.92:
            continue
        p = max(3, int(0.12 * h))
        inner = bw[y + p:y + h - p, x + p:x + w - p]
        if inner.size == 0 or inner.mean() > 0.35 or inner.mean() < 0.01:
            continue
        t, sc = rec([x + p, y + p, x + w - p, y + h - p])
        m = BOXED.fullmatch(t.replace(" ", ""))
        if sc > 0.5 and m:
            out.append(([x - 4, y - 4, x + w + 4, y + h + 4], m.group(1)))
    return out


# ------------------------------------------------------------ <보기> 의 ㄱ, ㄴ, ㄷ
JAMO = "ㄱㄴㄷㄹ"
_jamo_t = None


def _shape_vec(a, n=24):
    """검은 점 배열 → 테두리에 맞춰 n×n 으로 키운 비교용 벡터 (가로세로 비율 포함)"""
    ys, xs = np.nonzero(a)
    if len(xs) < 4:
        return None
    a = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    v = np.asarray(Image.fromarray(a.astype(np.uint8) * 255).resize((n, n), Image.BILINEAR), float) / 255
    v = np.concatenate([v.ravel(), [a.shape[1] / a.shape[0] * 3]])
    v = v - v.mean()
    return v / (np.linalg.norm(v) + 1e-6)


def jamo_templates():
    global _jamo_t
    if _jamo_t is None:
        _jamo_t = []
        for d in FONT_DIRS:
            for f in FONT_FILES:
                path = os.path.join(d, f)
                if not os.path.exists(path):
                    continue
                try:
                    font = ImageFont.truetype(path, 80)
                except OSError:
                    continue
                for ch in JAMO:
                    a = _render(font, ch)
                    v = _shape_vec(a) if a is not None else None
                    if v is not None:
                        _jamo_t.append((ch, v))
    return _jamo_t


def _jamo_rule(a):
    """획 위치로 ㄱ/ㄴ/ㄷ/ㄹ 구분 (작게 캡처해 흐려져도 견본 비교보다 안정적). 모르겠으면 None"""
    ys, xs = np.nonzero(a)
    if len(xs) < 6:
        return None
    a = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = a.shape
    if h < 4 or w < 4:
        return None
    t, b = max(1, round(h * 0.25)), max(1, round(h * 0.25))
    right, left = slice(round(w * 0.6), w), slice(0, max(1, round(w * 0.4)))
    top_right = a[:t, right].mean() > 0.15
    bot_left = a[h - b:, left].mean() > 0.15
    mid_right = a[round(h * 0.4):round(h * 0.6) + 1, right].mean() > 0.15
    mid_center = a[round(h * 0.4):round(h * 0.6) + 1, round(w * 0.3):round(w * 0.7) + 1].mean() > 0.25
    if top_right and not bot_left:
        return "ㄱ"
    if bot_left and not top_right:
        return "ㄴ"
    if top_right and bot_left:
        return "ㄹ" if (mid_center and mid_right) else "ㄷ"
    return None


def read_jamo_choices(g, choices, lh):
    """<보기> 문제의 보기 ①~⑤ 오른쪽 값을 ㄱ, ㄴ, ㄷ 로 읽는다 (OCR 은 ㄱ→7, ㄴ→L, ㄷ→C 로 읽음).
    choices: [(box, '①'), …]. 결과 [(box, 'ㄱ, ㄴ'), …] — 값 자리 전체를 덮는 박스"""
    import cv2
    T = jamo_templates()
    if not T:
        return []
    # 연한 회색까지 글자로 보고 1px 닫기: 작게 캡처해 키운 그림은 가는 가로획이 끊어짐
    bw = cv2.morphologyEx((g < 200).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
    out = []
    cs = sorted(choices, key=lambda c: c[0][0])
    for box, _ch in cs:
        cy, h = (box[1] + box[3]) / 2, box[3] - box[1]
        nxt = [b for b, _ in cs if b[0] > box[2] and abs((b[1] + b[3]) / 2 - cy) < 0.5 * h]
        x0, x1 = box[2] + 1, (min(b[0] for b in nxt) - 1) if nxt else g.shape[1]
        y0, y1 = max(0, int(cy - 0.75 * h)), min(g.shape[0], int(cy + 0.75 * h))
        if x1 - x0 < 4:
            continue
        reg = bw[y0:y1, int(x0):int(x1)]
        n, lab, st, _ = cv2.connectedComponentsWithStats(reg, connectivity=8)
        # 가로로 겹치는 조각은 한 글자 (ㄷ 의 윗획처럼 떨어진 획)
        glyphs = []
        for i in sorted(range(1, n), key=lambda i: st[i][0]):
            x, y, w, hh, a = st[i]
            if a <= 3:
                continue
            gl = glyphs[-1] if glyphs else None
            if gl and min(gl[2], x + w) - max(gl[0], x) > 0.5 * min(w, gl[2] - gl[0]):
                gl[0], gl[1], gl[2], gl[3] = min(gl[0], x), min(gl[1], y), max(gl[2], x + w), max(gl[3], y + hh)
                gl[4].append(i)
            else:
                glyphs.append([x, y, x + w, y + hh, [i]])
        chars, last_x = [], None
        for gx0, gy0, gx1, gy1, ids in glyphs:
            if last_x is not None and gx0 - last_x > 3 * lh:  # 너무 멀면 다른 보기(같은 줄)
                break
            if gy1 - gy0 < 0.25 * lh:
                continue  # 쉼표, 점
            v = _shape_vec(np.isin(lab[gy0:gy1, gx0:gx1], ids))
            if v is None:
                continue
            score, jm = max((float(v @ t), c) for c, t in T)
            rule = _jamo_rule(np.isin(lab[gy0:gy1, gx0:gx1], ids))
            if rule:
                jm, score = rule, max(score, 0.3)
            if score < 0.3:  # ㄱㄴㄷ 이 아닌 것이 있으면 이 보기는 OCR 에 맡김
                chars = []; break
            chars.append(jm); last_x = gx1
        if chars:
            out.append(([int(x0), y0, int(x0) + int(last_x) + 2, y1], ", ".join(chars)))
    return out


def read_jamo_label(g, box, lh):
    """<보기> 안의 'ㄱ.' 'ㄴ.' 'ㄷ.' 줄머리 (OCR 은 7. L. C. 로 읽거나 빠뜨림).
    box: 줄머리 OCR 단어 박스. 결과 (박스, 'ㄱ.') 또는 None"""
    import cv2
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    x1 = min(x1, x0 + int(1.6 * lh))
    reg = cv2.morphologyEx((g[y0:y1, x0:x1] < 200).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(reg, connectivity=8)
    parts = sorted((st[i][0], i) for i in range(1, n) if st[i][4] > 3)
    if not parts:
        return None
    gx0 = parts[0][0]
    ids = [i for x, i in parts if x < gx0 + 0.9 * lh and st[i][3] >= 0.15 * lh and
           min(gx0 + 0.9 * lh, x + st[i][2]) - x > 0.5 * st[i][2]]
    if not ids:
        return None
    gx1 = max(st[i][0] + st[i][2] for i in ids)
    gy0 = min(st[i][1] for i in ids); gy1 = max(st[i][1] + st[i][3] for i in ids)
    if gy1 - gy0 < 0.25 * lh:
        return None
    jm = _jamo_rule(np.isin(lab[gy0:gy1, gx0:gx1], ids))
    if not jm:
        return None
    # 바로 뒤의 작은 점
    dots = [i for x, i in parts if i not in ids and gx1 <= x < gx1 + 0.5 * lh and st[i][3] < 0.3 * lh]
    right = max([gx1] + [st[i][0] + st[i][2] for i in dots])
    return [x0 + gx0 - 1, y0, x0 + right + 2, y1], jm + "."
