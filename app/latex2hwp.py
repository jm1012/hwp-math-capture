"""LaTeX 수식을 한글(HWP) 수식 편집기 스크립트로 변환한다.

    >>> latex_to_hwp(r"\\frac{-b\\pm\\sqrt{b^2-4ac}}{2a}")
    '{-b +- sqrt {b ^{2} -4 a c}} over {2 a}'

한글 수식 문법 요약
- 분수 `{a} over {b}`, 제곱근 `sqrt {x}`, n제곱근 `root {n} of {x}`
- 첨자 `x ^{2}`, `a _{n}`, 괄호 크기 조절 `LEFT ( ... RIGHT )`
- 행렬 `pmatrix{a & b # c & d}`, 경우 `cases{...}`
- 공백은 무시되므로(토큰 구분용) 보이는 공백은 `~`, 좁은 공백은 `` ` ``
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------- 기호 표
GREEK = """alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi
omicron pi rho sigma tau upsilon phi chi psi omega""".split()

SYMBOLS = {
    # 연산자
    "pm": "+-", "mp": "-+", "times": "times", "div": "÷", "cdot": "cdot",
    "ast": "AST", "star": "STAR", "circ": "CIRC", "bullet": "BULLET",
    "oplus": "OPLUS", "ominus": "OMINUS", "otimes": "OTIMES", "odot": "ODOT",
    # 관계
    "le": "LEQ", "leq": "LEQ", "leqslant": "LEQ", "ge": "GEQ", "geq": "GEQ", "geqslant": "GEQ",
    "ne": "!=", "neq": "!=", "approx": "APPROX", "equiv": "==", "sim": "SIM",
    "simeq": "SIMEQ", "cong": "CONG", "propto": "PROPTO", "ll": "<<", "gg": ">>",
    "doteq": "DOTEQ", "fallingdotseq": "image", "risingdotseq": "REIMAGE",
    "prec": "PREC", "succ": "SUCC", "perp": "BOT", "bot": "BOT", "top": "TOP",
    "parallel": "∥", "mid": "` | `", "vdash": "VDASH", "models": "MODELS",
    # 집합, 논리
    "in": "IN", "notin": "NOTIN", "ni": "OWNS", "owns": "OWNS",
    "subset": "SUBSET", "subseteq": "SUBSETEQ", "supset": "SUPERSET", "supseteq": "SUPSETEQ",
    "subsetneq": "⊊", "supsetneq": "⊋", "nsubset": "⊄", "not\\subset": "⊄",
    "cap": "∩", "cup": "∪", "setminus": "-", "emptyset": "EMPTYSET", "varnothing": "EMPTYSET",
    "forall": "FORALL", "exists": "EXIST", "nexists": "∄", "neg": "¬", "lnot": "¬",
    "land": "LAND", "wedge": "LAND", "lor": "LOR", "vee": "LOR",
    "therefore": "THEREFORE", "because": "BECAUSE",
    # 화살표
    "to": "->", "rightarrow": "->", "longrightarrow": "->", "leftarrow": "larrow",
    "gets": "larrow", "longleftarrow": "larrow", "leftrightarrow": "<->",
    "Rightarrow": "RARROW", "Longrightarrow": "RARROW", "implies": "RARROW",
    "Leftarrow": "LARROW", "Longleftarrow": "LARROW",
    "Leftrightarrow": "LRARROW", "Longleftrightarrow": "LRARROW", "iff": "LRARROW",
    "uparrow": "uparrow", "downarrow": "downarrow", "Uparrow": "UPARROW",
    "Downarrow": "DOWNARROW", "mapsto": "MAPSTO",
    "nearrow": "NEARROW", "searrow": "SEARROW", "nwarrow": "NWARROW", "swarrow": "SWARROW",
    # 기타
    "infty": "INF", "partial": "partial", "nabla": "NABLA", "angle": "ANGLE",
    "measuredangle": "MSANGLE", "triangle": "TRIANGLE", "bigtriangleup": "TRIANGLE",
    "square": "□", "Box": "□", "diamond": "DIAMOND", "prime": "prime",
    "cdots": "CDOTS", "ldots": "LDOTS", "dots": "LDOTS", "dotsc": "LDOTS", "dotsb": "CDOTS",
    "vdots": "VDOTS", "ddots": "DDOTS", "degree": "DEG", "hbar": "ℏ", "ell": "ℓ",
    "Re": "ℜ", "Im": "ℑ", "aleph": "ℵ", "wp": "℘", "dagger": "DAGGER",
    "lfloor": "⌊", "rfloor": "⌋", "lceil": "⌈", "rceil": "⌉",
    "langle": "〈", "rangle": "〉", "vert": "|", "Vert": "∥", "lvert": "|", "rvert": "|",
    "lVert": "∥", "rVert": "∥", "backslash": "∖",
}
# \{ 같은 한 글자 이스케이프
ESCAPED = {"{": "lbrace", "}": "rbrace", "|": "∥", "%": "%", "$": "$", "#": "#",
           "&": "&", "_": "_"}
SPACES = {",": "`", ":": "`", ";": "`", ">": "`", "!": "", " ": "~",
          "quad": "~", "qquad": "~~", "enspace": "`", "thinspace": "`", "medspace": "`",
          "thickspace": "`", "space": "~", "hspace": "~"}
# 큰 연산자 (아래/위 첨자를 받음)
BIG_OPS = {"sum": "sum", "prod": "prod", "coprod": "coprod", "int": "int", "iint": "dint",
           "iiint": "tint", "oint": "oint", "bigcup": "union", "bigcap": "inter",
           "bigoplus": "BIGOPLUS", "bigotimes": "BIGOTIMES", "lim": "lim",
           "limsup": "lim sup", "liminf": "lim inf"}
FUNCS = """sin cos tan csc sec cot sinh cosh tanh coth arcsin arccos arctan log ln lg exp
max min sup inf det gcd lcm deg dim ker arg hom Pr mod""".split()
ACCENTS = {"vec": "vec", "overrightarrow": "vec", "overleftrightarrow": "dyad",
           "bar": "bar", "overline": "bar", "hat": "hat", "widehat": "hat",
           "tilde": "tilde", "widetilde": "tilde", "dot": "dot", "ddot": "ddot",
           "acute": "acute", "grave": "grave", "check": "check", "breve": "arch",
           "underline": "under", "boxed": "BOX", "fbox": "BOX", "framebox": "BOX"}
ENVS = {"matrix": "matrix", "pmatrix": "pmatrix", "bmatrix": "bmatrix",
        "vmatrix": "dmatrix", "Vmatrix": "dmatrix", "smallmatrix": "matrix",
        "cases": "cases", "aligned": "eqalign", "align": "eqalign", "align*": "eqalign",
        "gathered": "eqalign", "split": "eqalign", "array": "matrix", "eqnarray": "eqalign"}
DROP = {"displaystyle", "textstyle", "scriptstyle", "limits", "nolimits", "left.",
        "right.", "big", "Big", "bigg", "Bigg", "bigl", "bigr", "Bigl", "Bigr",
        "biggl", "biggr", "Biggl", "Biggr", "nonumber", "notag", "mathstrut", "strut",
        # 글자 크기 명령: 한글 수식에 없는 문법이고, 인식기가 작은 글씨(점 이름 등)에 붙여 내는 것이라 버림
        "scriptscriptstyle", "tiny", "scriptsize", "footnotesize", "small", "normalsize", "large", "Large",
        "LARGE", "huge", "Huge"}
FONT_CMDS = {"mathrm": "rm", "textrm": "rm", "mathit": "it", "mathbf": "bold",
             "textbf": "bold", "boldsymbol": "bold", "bm": "bold", "mathbb": "",
             "mathcal": "", "mathscr": "", "mathfrak": "", "mathsf": "rm", "mathtt": "rm"}
TEXT_CMDS = {"text", "textup", "mbox", "hbox", "textit", "texttt", "textnormal"}
DELIMS = {"(": "(", ")": ")", "[": "[", "]": "]", "|": "|", "\\{": "lbrace", "\\}": "rbrace",
          "\\lbrace": "lbrace", "\\rbrace": "rbrace", "\\langle": "<", "\\rangle": ">",
          "\\|": "∥", "\\Vert": "∥", "\\vert": "|", "\\lfloor": "⌊", "\\rfloor": "⌋",
          "\\lceil": "⌈", "\\rceil": "⌉", "/": "/", "<": "<", ">": ">"}


# ---------------------------------------------------------------- 토큰화
TEXT_RE = r"\\(?:text|textup|mbox|hbox|textit|texttt|textnormal)\s*\{[^{}]*\}"
TOKEN_RE = re.compile(TEXT_RE + r"|\\[a-zA-Z]+\*?|\\.|[0-9]+(?:\.[0-9]+)?|\s+|.", re.S)


def tokenize(s: str) -> list[str]:
    return [t for t in TOKEN_RE.findall(s) if not t.isspace()]


class Parser:
    def __init__(self, tokens: list[str]):
        self.t = tokens
        self.i = 0

    # 기본 도구 -------------------------------------------------------
    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def next(self):
        tok = self.peek()
        self.i += 1
        return tok

    def raw_group(self) -> str:
        """{...} 안의 원문(문자열)을 그대로 돌려준다 (\\text 용)."""
        if self.peek() != "{":
            return self.next() or ""
        self.next()
        depth, out = 1, []
        while self.peek() is not None:
            tok = self.next()
            if tok == "{":
                depth += 1
            elif tok == "}":
                depth -= 1
                if depth == 0:
                    break
            out.append(tok)
        return "".join(out)

    def optional_arg(self):
        if self.peek() != "[":
            return None
        self.next()
        out = []
        while self.peek() not in (None, "]"):
            out.append(self.atom())
        self.next()
        return " ".join(x for x in out if x)

    def arg(self) -> str:
        """명령의 인자 하나: {그룹} 또는 토큰 하나."""
        if self.peek() == "{":
            self.next()
            body = self.sequence(stop={"}"})
            self.next()
            return body
        return self.atom()

    # 문법 ------------------------------------------------------------
    def sequence(self, stop=frozenset()) -> str:
        out = []
        while self.peek() is not None and self.peek() not in stop:
            if self.peek() in ("\\right", "\\end"):
                break
            a = self.atom()
            if a:
                out.append(a)
        return " ".join(out)

    def scripts(self, base: str) -> str:
        """base 뒤에 붙는 ^, _, ' 를 처리."""
        while self.peek() in ("^", "_", "'"):
            tok = self.next()
            if tok == "'":
                base += " prime"
                continue
            body = self.arg()
            base += f" {tok}{{{body}}}"
        return base

    def atom(self) -> str:
        tok = self.next()
        if tok is None:
            return ""
        if tok == "{":
            body = self.sequence(stop={"}"})
            self.next()
            return self.scripts(f"{{{body}}}")
        if tok in ("^", "_"):  # 앞에 밑이 없는 첨자
            self.i -= 1
            return self.scripts("{}")
        if tok == "'":
            return self.scripts("prime")
        if tok == "&":
            return "&"
        if tok == "~":
            return "~"
        if tok == "\\\\":
            self.optional_arg()
            return "#"
        if re.fullmatch(TEXT_RE, tok):
            text = tok[tok.index("{") + 1:-1].replace('"', "'")
            return self.scripts(f'"{text}"')
        if tok.startswith("\\"):
            return self.command(tok)
        if tok == "-":
            return "-"
        if tok in "<>" and self.peek() == "=":
            self.next()
            return "LEQ" if tok == "<" else "GEQ"
        return self.scripts(tok)

    def command(self, tok: str) -> str:
        name = tok[1:]
        if name in DROP:
            return ""
        if len(name) == 1 and not name.isalpha():
            if name in SPACES:
                return SPACES[name]
            if name == "\\":
                return "#"
            return self.scripts(ESCAPED.get(name, name))
        if name in SPACES:
            if name == "hspace":
                self.raw_group()
            return SPACES[name]
        if name in ("frac", "dfrac", "tfrac", "cfrac"):
            a, b = self.arg(), self.arg()
            return self.scripts(f"{{{{{a}}} over {{{b}}}}}")
        if name in ("binom", "dbinom", "tbinom"):
            a, b = self.arg(), self.arg()
            return self.scripts(f"LEFT ( {{{a}}} atop {{{b}}} RIGHT )")
        if name == "sqrt":
            n = self.optional_arg()
            x = self.arg()
            return self.scripts(f"root {{{n}}} of {{{x}}}" if n else f"sqrt {{{x}}}")
        if name in BIG_OPS:
            return self.scripts(BIG_OPS[name])
        if name in ("operatorname", "operatorname*"):
            fname = re.sub(r"[\s{}\\]", "", self.raw_group())
            if fname in BIG_OPS:
                return self.scripts(BIG_OPS[fname])
            return self.scripts(fname if fname in FUNCS else f"{{rm {fname}}}")
        if name in FUNCS:
            return self.scripts(name)
        if name in GREEK:
            return self.scripts(name)
        if name[:3] == "var" and name[3:] in GREEK:
            return self.scripts(name[3:])
        if name.lower() in GREEK and name[0].isupper():
            return self.scripts(name.upper())
        if name in ACCENTS:
            return self.scripts(f"{ACCENTS[name]} {{{self.arg()}}}")
        if name == "overset":
            top, base = self.arg(), self.arg()
            if top in ("frown", "⌢"):
                return self.scripts(f"arch {{{base}}}")
            return self.scripts(f"{{{base}}} ^{{{top}}}")
        if name == "underset":
            bot, base = self.arg(), self.arg()
            return self.scripts(f"{{{base}}} _{{{bot}}}")
        if name in ("overbrace", "underbrace"):
            body = self.arg()
            return self.scripts(f"{name.upper()} {{{body}}}")
        if name in ("stackrel",):
            top, base = self.arg(), self.arg()
            return self.scripts(f"{{{base}}} ^{{{top}}}")
        if name in ("not",):
            nxt = self.peek()
            if nxt in ("\\in",):
                self.next()
                return "NOTIN"
            if nxt in ("=",):
                self.next()
                return "!="
            return ""
        if name in FONT_CMDS:
            body = self.arg()
            kw = FONT_CMDS[name]
            return self.scripts(f"{{{kw} {body}}}" if kw else body)
        if name in TEXT_CMDS:
            text = self.raw_group().replace('"', "'")
            return self.scripts(f'"{text}"')
        if name == "left":
            return self.left_right()
        if name == "begin":
            return self.environment()
        if name in ("frown",):
            return "frown"
        if name in SYMBOLS:
            return self.scripts(SYMBOLS[name])
        # 모르는 명령: 이름을 그대로 남긴다 (한글이 알아듣는 경우가 많음)
        return self.scripts(name)

    def delim(self, tok):
        if tok == ".":
            return None
        return DELIMS.get(tok, tok.lstrip("\\"))

    def left_right(self) -> str:
        ld = self.delim(self.next())
        body = self.sequence()
        rd = None
        if self.peek() == "\\right":
            self.next()
            rd = self.delim(self.next())
        if ld is None or rd is None:
            # 한쪽만 있는 괄호(예: \left\{ ... \right.)
            if ld is None and rd is None:
                return self.scripts(f"{{{body}}}")
            if ld is None:
                return self.scripts(f"{{{body}}} {rd}")
            return self.scripts(f"{ld} {{{body}}}")
        return self.scripts(f"LEFT {ld} {body} RIGHT {rd}")

    def environment(self) -> str:
        env = self.raw_group()
        if env == "array":
            self.raw_group()  # 열 정렬 지정 {cc} 무시
        body = self.sequence()
        if self.peek() == "\\end":
            self.next()
            self.raw_group()
        kw = ENVS.get(env, "matrix")
        body = re.sub(r"\s*#\s*$", "", body)
        return self.scripts(f"{kw}{{{body}}}")


# ---------------------------------------------------------------- 공개 함수
def clean_latex(s: str) -> str:
    s = s.strip()
    for a, b in (("$$", "$$"), ("\\[", "\\]"), ("\\(", "\\)"), ("$", "$")):
        if s.startswith(a) and s.endswith(b) and len(s) >= len(a) + len(b):
            s = s[len(a):len(s) - len(b)].strip()
            break
    return s


def tidy(h: str) -> str:
    h = re.sub(r"\s+", " ", h).strip()
    h = re.sub(r"\{ ", "{", h)
    h = re.sub(r" \}", "}", h)
    h = re.sub(r" ([\^_])\{", r" \1{", h)
    # 빼기 부호는 뒤 피연산자와 붙여 써서 보기 좋게
    h = re.sub(r"(^|[{(] ?|= |\+- )- ", lambda m: m.group(1) + "-", h)
    return h


def latex_to_hwp(latex: str) -> str:
    return tidy(Parser(tokenize(clean_latex(latex))).sequence())


if __name__ == "__main__":
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
    print(latex_to_hwp(src))
