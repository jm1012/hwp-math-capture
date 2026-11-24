"""한국어 띄어쓰기 교정 (quickspacer level 3 모델을 numpy 로 실행, TensorFlow 불필요)

글자 하나마다 "뒤에 공백이 올 확률"을 계산하는 작은 합성곱 모델이다.
지문 인식 결과의 문단에서 수식을 X 로 바꾼 문장을 통째로 넣어 띄어쓰기를 다시 매긴다.
"""
from __future__ import annotations

import os
import re
import sys

import numpy as np

DATA = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "spacing_data")


def _conv1d_same(x, k, b):
    n = k.shape[0]
    pl = (n - 1) // 2
    xp = np.pad(x, ((pl, n - 1 - pl), (0, 0)))
    out = np.zeros((x.shape[0], k.shape[2]), dtype=np.float32)
    for i in range(n):
        out += xp[i:i + x.shape[0]] @ k[i]
    return out + b


class Spacer:
    def __init__(self, data_dir: str = DATA):
        w = np.load(os.path.join(data_dir, "quickspacer3.npz"))
        g = lambda n: w[n].astype(np.float32)  # noqa: E731
        self.emb = g("embedding__embeddings")
        self.convs = [(g(f"conv1d{s}__kernel"), g(f"conv1d{s}__bias")) for s in ("", "_1", "_2", "_3", "_4")]
        with open(os.path.join(data_dir, "vocab.txt"), encoding="utf-8") as f:
            self.vocab = {line.rstrip("\n"): i for i, line in enumerate(f)}

    def _probs(self, s: str) -> np.ndarray:
        e = self.emb[np.array([self.vocab.get(c, 1) for c in s])]
        relu = lambda a: np.maximum(a, 0)  # noqa: E731
        o = [relu(_conv1d_same(e, *self.convs[i])) for i in range(3)]
        o = relu(_conv1d_same(np.concatenate([e] + o, 1), *self.convs[3]))
        o = _conv1d_same(o, *self.convs[4])[:, 0]
        return 1 / (1 + np.exp(-o))

    def space(self, s: str) -> str:
        """s 의 공백을 모두 지우고 새로 띄운다."""
        s = re.sub(r"\s+", "", s)
        if not s:
            return s
        p = self._probs(s)
        return fix_terms("".join(c + (" " if q > 0.5 else "") for c, q in zip(s, p)).strip())


# 수학 문제에서 자주 틀리는 부분 보정
TERMS = ("사분면 대칭이동 정사각형 직사각형 서로소 최댓값 최솟값 극댓값 극솟값 부정적분 정적분 등차수열 "
         "등비수열 이차방정식 이차함수 삼차함수 점근선 정의역 치역 공차 공비 좌표평면 수직선 자연수 정수 실수 "
         "유리수 무리수 양수 음수 접선 법선 원점 중점 꼭짓점 넓이 둘레 확률 기댓값 평균 분산 표준편차 대입 "
         "성립 만족 확률변수 이산확률변수 연속확률변수 확률분포 정규분포 표준정규분포 이항분포 표본평균 모평균 "
         "첫째항 일반항 조건부확률 여사건 중복조합 이등변삼각형 직각삼각형 정삼각형 평행사변형 사차함수 "
         "삼각함수 로그함수 지수함수 역함수 합성함수 도함수 이계도함수 미분계수 평균변화율").split()
# 긴 용어부터 (이산확률변수 → 확률변수 순서)
_TERM_RE = [(re.compile(r"\s?".join(map(re.escape, t))), t) for t in sorted(dict.fromkeys(TERMS), key=len, reverse=True)]


def _term_sub(t):
    def f(m):
        # 모델이 "항이자 연수인" 처럼 공백을 용어 속에 잘못 넣었으면, 그 공백을 용어 앞으로 옮긴다 (→ "항이 자연수인")
        moved = " " in m.group(0) and m.start() > 0 and re.match(r"[가-힣]", m.string[m.start() - 1])
        return (" " if moved else "") + t
    return f


def fix_terms(s: str) -> str:
    s = re.sub(r"(\d) (?=[가-힣])(?!이상|이하|미만|초과)", r"\1", s)  # 2 인 → 2인
    s = re.sub(r"(\d)(?=이상|이하|미만|초과)", r"\1 ", s)  # 2이상 → 2 이상
    s = re.sub(r" +(?=[?.,)\]])", "", s)                         # 값은 ? → 값은?
    s = re.sub(r"(?<=[^\s(\[])(?=\[\d+점\])", " ", s)            # 구하시오.[3점] → 구하시오. [3점]
    s = s.replace("서로소 인", "서로소인").replace("인자연수", "인 자연수")
    s = re.sub(r",(?=\S)", ", ", s)                             # 쉼표 뒤는 띄움
    s = re.sub(r"(?<=[가-힣][?.])(?=\()", " ", s)                 # 값은?(단, → 값은? (단,
    s = re.sub(r"X(?=(위|아래|사이)[의에 ])", "X ", s)            # X 위의 점
    s = re.sub(r"제 ?(\d) ?사분면", r"제\1사분면", s)
    for pat, t in _TERM_RE:
        s = pat.sub(_term_sub(t), s)
    return s


def respace_paragraph(spacer: Spacer, segs, after_math: bool = False):
    """[("text", …), ("math", …)] 문단의 띄어쓰기를 다시 매긴다. 수식은 X 한 글자로 넣어 문맥만 준다.
    after_math: 바로 앞 문단이 수식으로 끝남 (여러 줄 수식 뒤 "가 실수 전체의 …" 처럼 조사로 시작하는 문단에 문맥을 줌)"""
    if not any(k == "text" and re.search(r"[가-힣]", v) for k, v in segs):
        return segs
    if re.match(r"\s*[①-⑤]", next((v for k, v in segs if k == "text"), "")):
        return segs  # 보기 줄은 그대로
    units = []  # (seg 번호, 글자) — 수식은 ("X")
    for i, (k, v) in enumerate(segs):
        if k == "math":
            units.append((i, "X"))
        else:
            units += [(i, c) for c in v if not c.isspace()]
    lead = after_math and bool(units) and units[0][1] != "X"
    spaced = spacer.space(("X" if lead else "") + "".join(c for _, c in units))
    if lead:
        spaced = spaced[1:].lstrip()
    # spaced 의 공백 아닌 글자는 units 와 1:1
    out, j, gap = [], 0, False
    for c in spaced:
        if c == " ":
            gap = True
            continue
        i, _ = units[j]
        j += 1
        k, v = segs[i]
        if gap:
            if out and out[-1][0] == "text":
                out[-1] = ("text", out[-1][1] + " ")
            else:
                out.append(("text", " "))
            gap = False
        if k == "math":
            out.append(("math", v))
        elif out and out[-1][0] == "text":
            out[-1] = ("text", out[-1][1] + c)
        else:
            out.append(("text", c))
    return out


# ---------------------------------------------------------------- PDF 글자 정보로 띄어쓰기
_HANGUL = re.compile(r"[가-힣]")


def _ref_gaps(chars):
    """PDF 글자들 [(상자 또는 None, 글자)] (읽는 차례, 문제 밖 글자는 None 글자로) →
    (한글 글자열, 한글 글자 사이마다 True=띄움 / False=붙임 / None=모름).
    사이에 공백만 있으면 띄움, 아무것도 없으면 붙임(글자 정보에 공백이 없는 PDF 는 간격으로 판단),
    수식 글자·문장 부호·줄바꿈이 끼었으면 모름."""
    # 글자 정보에 공백 글자가 들어 있는 PDF(한글 등에서 만든 것)는 공백이 없으면 붙임. 글자 상자는 글자 모양에 딱 맞아
    # 같은 단어 안에서도 간격이 들쭉날쭉하므로, 공백 글자가 없는 PDF 에서만 간격으로 판단
    explicit = sum(1 for _, c in chars if c == " ") >= 3
    hs, gaps = [], []
    prev, between = None, "none"
    for box, c in chars:
        if c is not None and _HANGUL.match(c):
            if prev is not None:
                g = None
                if between == "space":
                    g = True
                elif between == "none" and explicit:
                    g = False
                elif between == "none" and box is not None and prev is not None and prev[0] is not None:
                    pb = prev[0]
                    h = max(pb[3] - pb[1], box[3] - box[1])
                    if min(pb[3], box[3]) - max(pb[1], box[1]) > 0.5 * h:  # 같은 줄
                        gap = box[0] - pb[2]
                        g = False if gap < 0.15 * h else True if gap > 0.3 * h else None
                gaps.append(g)
            hs.append(c)
            prev, between = (box, c), "none"
        elif c is not None and c.isspace() and c not in "\r\n":
            between = "space" if between in ("none", "space") else "other"
        else:
            between = "other"
    return "".join(hs), gaps


def respace_from_pdf(paras, chars, min_run: int = 3):
    """인식 결과 문단들의 한글 사이 띄어쓰기를 PDF 글자 정보(chars: _ref_gaps 참고)에 맞춘다.
    인식 글자와 PDF 글자가 min_run 글자 넘게 이어서 같은 곳만 바꾸고, 나머지는 그대로 둔다."""
    import difflib
    ref, gaps = _ref_gaps(chars)
    if len(ref) < min_run:
        return paras
    # 결과의 한글 글자 위치: (문단, 조각, 글자 자리)
    pos = []
    for pi, para in enumerate(paras or []):
        for si, (k, v) in enumerate(para):
            if k == "text":
                pos += [(pi, si, ci) for ci, c in enumerate(v) if _HANGUL.match(c)]
    out = "".join(paras[pi][si][1][ci] for pi, si, ci in pos)
    sm = difflib.SequenceMatcher(None, out, ref, autojunk=False)
    want = {}  # 결과 글자 번호 i → (i 와 i+1 사이 띄움 여부)
    for a, b, n in sm.get_matching_blocks():
        if n < min_run:
            continue
        for t in range(n - 1):
            g = gaps[b + t]
            if g is not None:
                want[a + t] = g
    if not want:
        return paras
    edits = {}  # (문단, 조각) → [(시작, 끝, 바꿀 글)]
    for i, g in want.items():
        (pi, si, ci), (pj, sj, cj) = pos[i], pos[i + 1]
        if (pi, si) != (pj, sj):
            continue
        between = paras[pi][si][1][ci + 1:cj]
        if between.strip():  # 사이에 다른 글자가 있으면 손대지 않음
            continue
        new = " " if g else ""
        if between != new:
            edits.setdefault((pi, si), []).append((ci + 1, cj, new))
    if not edits:
        return paras
    out_paras = []
    for pi, para in enumerate(paras):
        segs = []
        for si, (k, v) in enumerate(para):
            for s0, s1, new in sorted(edits.get((pi, si), []), reverse=True):
                v = v[:s0] + new + v[s1:]
            segs.append((k, v))
        out_paras.append(segs)
    return out_paras
