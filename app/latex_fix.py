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
    # 글자 크기 명령과 그 뒤 공백 제거: \mathrm { \scriptsize ~ A } -> \mathrm { A }
    s = re.sub(r"\\(?:scriptscriptstyle|tiny|scriptsize|footnotesize|small|normalsize|large|Large|LARGE|huge|Huge)"
               r"(?![A-Za-z])(?:\s|~|\\[,;:! ])*", "", s)
    # 빈 첨자: a _ { n } ^ { } -> a _ { n } (한글에서 빈 칸 첨자가 생김)
    s = re.sub(r"\s*[\^_]\s*\{\s*\}", "", s)
    # 글꼴 묶음 맨 앞의 공백: \mathrm { ~ A } -> \mathrm { A }
    s = re.sub(r"(\\(?:mathrm|textrm|mathit|mathbf|mathsf|operatorname)\s*\{)(?:\s|~|\\[,;:! ])+", r"\1", s)
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

# 숫자 0 과 알파벳 O 구분: 0(영) 뒤에는 은/을/과/이, O(오) 뒤에는 는/를/와/가 가 붙는다
_ZERO_AS_O = re.compile(r"(?<![0-9A-Za-z.])0(?=\s?[는를와가](?![가-힣]*\d))")


def zero_to_o(segs):
    return [(k, _ZERO_AS_O.sub("O", v) if k == "text" else v) for k, v in segs]


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
        mo = re.fullmatch(r"[_^]\s*(.*)", b.strip(), re.S)
        if mo:  # \overset{x}{_ 0}: 밑글자 없이 첨자만 있는 엉터리 (적분 구간에서 나옴) → 첨자 내용만
            return _group(mo.group(1), 0)[0]
        if re.match(r"\\(sum|prod|int|lim|bigcup|bigcap)(?![A-Za-z])", b.strip()):
            return f"{b.strip()}^{{{a}}}"
        return f"\\overset{{{a}}}{{{b}}}"
    s = _rewrite(s, "underset", under, 2)
    if "\\overset" in s:
        s = re.sub(r"\\overset(?=\s*\{)", r"\\OVERSET", s)
        s = _rewrite(s, "OVERSET", over, 2)
        s = s.replace("\\overset", "\\overset")
    # 왼쪽 중괄호 + array/matrix → cases (구간별 함수), cases 속 빈 줄 제거
    s = brace_to_cases(s)
    s = re.sub(r"\\begin\{cases\}(.*?)\\end\{cases\}", lambda m: "\\begin{cases}" + _rows(m.group(1)) + "\\end{cases}",
               s, flags=re.S)
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


# ---- 왼쪽 중괄호 + 표(array/matrix/aligned) → cases (구간별 함수) ----
# 중괄호 + 행렬은 수능 문제에 거의 나오지 않으므로, 왼쪽 중괄호 뒤의 표는 구간 중괄호로 본다.
# 단, 오른쪽 중괄호(\\right\\})까지 있으면 집합/행렬로 보고 그대로 둔다.
_BRACE_START = re.compile(
    r"(\{\s*)?(?:\\left|\\[Bb]igg?l?|\\[Bb]igl?)?\s*\\\{\s*(\}\s*)?(?:\\[!,;:]\s*)*(\{\s*)?\\begin\{(array|matrix|aligned)\}")


def _rows(body: str) -> str:
    """표 내용 → cases 내용: 열 지정 { l l } 과 빈 줄({ } & { }) 제거"""
    body = re.sub(r"^\s*\{[lcr\s|]*\}", "", body)
    rows = [r.strip() for r in re.split(r"\\\\", body)]
    keep = [r for r in rows if re.sub(r"[{}&\s]|\\[,;:! ]|\\q?quad", "", r)]
    return " \\\\ ".join(keep)


def brace_to_cases(s: str) -> str:
    pos = 0
    while True:
        m = _BRACE_START.search(s, pos)
        if not m:
            return s
        env = m.group(4)
        tok = re.compile(r"\\(begin|end)\{" + env + r"\}")
        depth, i = 1, m.end()
        while depth:
            t = tok.search(s, i)
            if not t:
                return s
            depth += 1 if t.group(1) == "begin" else -1
            i = t.end()
        body = s[m.end():i - len("\\end{%s}" % env)]
        j = i
        # \begin 앞에 연 { 와, 중괄호를 감싼 { (닫는 } 가 \{ 바로 뒤에 없을 때) 의 짝을 닫음
        for opened in (m.group(3), m.group(1) if not m.group(2) else None):
            if opened:
                t = re.compile(r"\s*\}").match(s, j)
                if t:
                    j = t.end()
        r = re.compile(r"\s*\\right\s*(\.|\\\}|\\rbrace)").match(s, j)
        if r and r.group(1) != ".":
            pos = m.end()
            continue
        if r:
            j = r.end()
        new = "\\begin{cases}" + _rows(body) + "\\end{cases}"
        s = s[:m.start()] + new + s[j:]
        pos = m.start() + len(new)
