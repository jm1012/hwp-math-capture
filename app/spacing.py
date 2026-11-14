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
         "성립 만족").split()
_TERM_RE = [(re.compile(r"\s?".join(map(re.escape, t))), t) for t in TERMS]


def fix_terms(s: str) -> str:
    s = re.sub(r"(\d) (?=[가-힣])(?!이상|이하|미만|초과)", r"\1", s)  # 2 인 → 2인
    s = re.sub(r"(\d)(?=이상|이하|미만|초과)", r"\1 ", s)  # 2이상 → 2 이상
    s = re.sub(r" +(?=[?.,)\]])", "", s)                         # 값은 ? → 값은?
    s = re.sub(r"(?<=[^\s(\[])(?=\[\d+점\])", " ", s)            # 구하시오.[3점] → 구하시오. [3점]
    s = s.replace("서로소 인", "서로소인").replace("인자연수", "인 자연수")
    s = re.sub(r",(?=\S)", ", ", s)                             # 쉼표 뒤는 띄움
    s = re.sub(r"X(?=(위|아래|사이)[의에 ])", "X ", s)            # X 위의 점
    s = re.sub(r"제 ?(\d) ?사분면", r"제\1사분면", s)
    for pat, t in _TERM_RE:
        s = pat.sub(t, s)
    return s


def respace_paragraph(spacer: Spacer, segs):
    """[("text", …), ("math", …)] 문단의 띄어쓰기를 다시 매긴다. 수식은 X 한 글자로 넣어 문맥만 준다."""
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
    spaced = spacer.space("".join(c for _, c in units))
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
