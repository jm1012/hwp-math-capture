"""latex2hwp 변환 확인 (python test_latex2hwp.py). v2.0.3 에서 고친 것 위주."""
from latex2hwp import latex_to_hwp

CASES = [
    # 벡터: \stackrel / \overset 위의 화살표는 vec
    (r"\stackrel { \rightharpoonup } { p } - \stackrel { \rightarrow } { a }", "vec {p} - vec {a}"),
    (r"\overset{\rightarrow}{AB}", "vec {A B}"),
    (r"\vec{a}+\overrightarrow{AB}", "vec {a} + vec {A B}"),
    (r"\overset{\frown}{AB}", "arch {A B}"),
    (r"\stackrel{def}{=}", "{=} ^{d e f}"),
    # 뜻 없는 명령은 인수와 함께 버림
    (r"a _ { 2 n } ^ { \phantom { 1 } } \big |", "a _{2 n} |"),
    (r"\sum b _ { n } \, \footnote { d i s }", "sum b _{n} `"),
    (r"\ref { m u l l } x", "x"),
    # 모르는 명령은 이름을 글자로 남기지 않음
    (r"x \triangleleft y \somethingunknown z", "x ◁ y z"),
    (r"f \colon X \to X", "f : X -> X"),
    (r"\textcircled { 1 } 3", "① 3"),
    (r"\lbrace a \rbrace \varPsi", "lbrace a rbrace PSI"),
    (r"x \hspace{1em} y", "x ~ y"),
    # 원래 되던 것
    (r"\frac{-b\pm\sqrt{b^2-4ac}}{2a}", "{{-b +- sqrt {b ^{2} - 4 a c}} over {2 a}}"),
    (r"\lim_{x \to 0} \frac{\sin x}{x}", "lim _{x -> 0} {{sin x} over {x}}"),
    (r"\begin{cases} -x^2 & (x<0) \\ x & (x \geq 0) \end{cases}", "cases{-x ^{2} & ( x < 0 ) # x & ( x GEQ 0 )}"),
]

if __name__ == "__main__":
    bad = 0
    for src, want in CASES:
        got = latex_to_hwp(src)
        if got != want:
            bad += 1
            print(f"FAIL {src}\n  want {want}\n  got  {got}")
    print(f"{len(CASES) - bad}/{len(CASES)} ok")
    raise SystemExit(1 if bad else 0)
