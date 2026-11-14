import random, sys, time, json
from sents import ALL

def bounds(s):
    """공백 앞 글자 위치 집합 (공백 제외 인덱스 기준)"""
    out, i = set(), 0
    for ch in s:
        if ch == " ": out.add(i)
        else: i += 1
    return out

def drop(s, p, seed):
    r = random.Random(seed)
    return "".join(c for c in s if not (c == " " and r.random() < p))

def score(fn, keep):
    tp = fp = fn_ = ex = 0; t = time.time()
    for i, g in enumerate(ALL):
        inp = drop(g, 1.0 if not keep else 0.5, i)
        out = fn(inp, keep)
        assert out.replace(" ", "") == g.replace(" ", ""), (out, g)
        a, b = bounds(out), bounds(g)
        tp += len(a & b); fp += len(a - b); fn_ += len(b - a); ex += out == g
    p = tp / (tp + fp or 1); r = tp / (tp + fn_ or 1)
    return dict(P=round(p, 3), R=round(r, 3), F1=round(2 * p * r / (p + r or 1), 3), exact=f"{ex}/{len(ALL)}",
                ms=round((time.time() - t) / len(ALL) * 1000, 1))

def show(fn, n=6):
    for g in ALL[:n]:
        print("   ", fn(g.replace(" ", ""), False))
