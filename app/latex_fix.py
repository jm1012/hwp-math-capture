"""인식 결과 후처리: Pix2Text 수식 표기 정리, 보기 번호(①~⑤), 한 글자 변수"""
from __future__ import annotations
import re

CIRC = "①②③④⑤"

def clean_latex(s: str) -> str:
    s = normalize_p2t(s.strip())
    # Pix2Text 는 토큰을 공백으로 나눔: \operatorname { s i n } -> \sin, 숫자 사이 공백 제거
    s = re.sub(r"\\operatorname\*?\s*\{\s*((?:[a-z]\s*)+)\}", lambda m: "\\" + m.group(1).replace(" ", ""), s)
    s = re.sub(r"(?<=\d) (?=\d)", "", s)
    s = re.sub(r"(?<=\d) (?=\d)", "", s)
    # 한 글자 수식이 위첨자로 나오는 경우: ^ { a } / { } ^ { a } -> a
    m = re.fullmatch(r"(?:\{\s*\}\s*)?\^\s*\{\s*(.+?)\s*\}", s)
    if m: s = m.group(1)
    s = re.sub(r"^\\mathbf\{\\(?:mu|Sigma)\}", "", s)
    return s.strip()

def fix_choices(segs):
    """①~⑤ 보기 줄에서 동그라미가 숫자로 읽힌 것을 되돌린다. segs: [(kind, val)]"""
    text = "".join(v for k, v in segs if k == "text")
    if sum(c in text for c in CIRC) < 2:
        return segs
    out, want_label, k = [], True, 1
    for kind, val in segs:
        if kind != "text":
            out.append((kind, val)); want_label = True; continue
        words = re.split(r"(\s+)", val); new = []
        for w in words:
            if not w.strip():
                new.append(w); continue
            if want_label and k <= 5 and w in (str(k), CIRC[k - 1]):
                new.append(CIRC[k - 1]); k += 1; want_label = False
            else:
                if w in CIRC: k = CIRC.index(w) + 2; want_label = False
                else: want_label = True
                new.append(w)
        out.append((kind, "".join(new)))
    return out

SINGLE = re.compile(r"(?<![A-Za-z가-힣])([A-Za-z])(?=[가-힣]|[\s,.)]|$)")

def single_letters(segs):
    """글자 속 한 글자 영문(변수)을 수식으로 바꾼다: '접선을l이라' -> 접선을 $l$이라"""
    out = []
    for kind, val in segs:
        if kind != "text":
            out.append((kind, val)); continue
        pos = 0
        for m in SINGLE.finditer(val):
            if m.start() > pos: out.append(("text", val[pos:m.start()]))
            out.append(("math", m.group(1))); pos = m.end()
        if pos < len(val): out.append(("text", val[pos:]))
    return out

def postprocess(lines):
    res = []
    for segs in lines:
        segs = [(k, clean_latex(v) if k == "math" else v) for k, v in segs]
        segs = fix_choices(segs)
        segs = single_letters(segs)
        res.append(segs)
    return res


# ---- Pix2Text 표기를 흔한 LaTeX 로 바꾸기 (latex2hwp 가 알아듣도록) ----
def _group(s, i):
    """s[i] 부터 공백을 건너뛰고 {…} 또는 토큰 하나를 읽어 (내용, 끝 위치) 반환"""
    while i < len(s) and s[i] == " ": i += 1
    if i >= len(s): return "", i
    if s[i] == "{":
        d = 0
        for j in range(i, len(s)):
            d += s[j] == "{"; d -= s[j] == "}"
            if d == 0: return s[i + 1:j].strip(), j + 1
        return s[i + 1:].strip(), len(s)
    if s[i] == "\\":
        m = re.match(r"\\([A-Za-z]+|.)", s[i:])
        return m.group(0), i + len(m.group(0))
    return s[i], i + 1

def _rewrite(s, cmd, fn, nargs):
    while True:
        m = re.search(r"\\" + cmd + r"(?![A-Za-z])", s)
        if not m: return s
        args, j = [], m.end()
        for _ in range(nargs):
            a, j = _group(s, j); args.append(a)
        s = s[:m.start()] + fn(*args) + s[j:]

def normalize_p2t(s: str) -> str:
    s = re.sub(r"\\mathop\s*\{\s*([^{}]*?)\s*\}", r"\1", s)
    s = re.sub(r"\\mathop\s*(?=[=+\-<>])", "", s)
    s = re.sub(r"\^\s*\{\s*\^\s*(\w)\s*\}", r"^{\1}", s)
    # \root n \of {x} -> \sqrt[n]{x}
    s = re.sub(r"\\root\s*(\S+)\s*\\of\s*", r"\\sqrt[\1]", s)
    def under(a, b):
        mo = re.fullmatch(r"\\overset\s*(.*)", b.strip(), re.S)
        if mo:
            sup, k = _group(mo.group(1), 0); base, _ = _group(mo.group(1), k)
            return f"{base}_{{{a}}}^{{{sup}}}"
        return f"{b}_{{{a}}}" if b.startswith("\\") else f"{{{b}}}_{{{a}}}"
    def over(a, b):
        mo = re.fullmatch(r"\\underset\s*(.*)", b.strip(), re.S)
        if mo:
            sub, k = _group(mo.group(1), 0); base, _ = _group(mo.group(1), k)
            return f"{base}_{{{sub}}}^{{{a}}}"
        if re.match(r"\\(sum|prod|int|lim|bigcup|bigcap)(?![A-Za-z])", b.strip()):
            return f"{b.strip()}^{{{a}}}"
        return f"\\overset{{{a}}}{{{b}}}"
    s = _rewrite(s, "underset", under, 2)
    if "\\overset" in s:
        s = re.sub(r"\\overset(?=\s*\{)", r"\\OVERSET", s)
        s = _rewrite(s, "OVERSET", over, 2)
        s = s.replace("\\overset", "\\overset")
    # 식 전체를 감싼 { … } 제거
    t = s.strip()
    while t.startswith("{"):
        g, e = _group(t, 0)
        if e != len(t): break
        t = g
    # \boldsymbol{a} -> a
    t = re.sub(r"\\boldsymbol\s*\{\s*([^{}]*?)\s*\}", r"\1", t)
    return t


# 수식 끝에 '이'가 기호처럼 잘못 붙어 나오는 흔한 모양 (o| , ∘[ , Φ| …)
_TAIL_I = re.compile(r"\s*(?:\\circ|\\Phi|\\phi|o|0|\\diamond)\s*(?:\\!\s*)?(?:\^\s*\{[^{}]*\}\s*)?[\[\]|]\s*$")


def split_tail(latex: str) -> tuple[str, str]:
    """수식 끝에 붙은 '이'를 떼어 (수식, 뒤에 붙일 글자) 로 돌려준다."""
    m = _TAIL_I.search(latex)
    if m and m.start() > 0:
        return latex[:m.start()].rstrip(), "이"
    return latex, ""
