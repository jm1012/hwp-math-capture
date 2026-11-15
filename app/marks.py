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
