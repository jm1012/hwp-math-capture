import json
T = json.load(open("/home/user/step1/imgs/truth.json"))
CASES = {k[:-3]: v for k, v in T.items() if k.endswith("_cm")}
CASES.update({
 "matrix": r"A=\begin{pmatrix}1&2\\3&4\end{pmatrix}",
 "det": r"\begin{vmatrix}a&b\\c&d\end{vmatrix}=ad-bc",
 "cases": r"f(x)=\begin{cases}x^{2} & (x\geq0)\\-x & (x<0)\end{cases}",
 "leftright": r"\left(\frac{1}{2}\right)^{n}",
 "abs": r"\left|x-\frac{1}{x}\right|\le 1",
 "text": r"P(A)=\frac{n(A)}{n(S)}\text{ (단, }n(S)\neq0)",
 "greekU": r"\Delta x \cdot \Sigma \Omega",
 "accent": r"\overline{AB}=\hat{y}+\tilde{z}+\bar{x}",
 "arc": r"\overset{\frown}{AB}",
 "prime2": r"f''(x)+g'(x)",
 "integral2": r"\int_{a}^{b}f(x)\,dx=\left[F(x)\right]_{a}^{b}",
 "texify_style": r"\operatorname*{lim}_{x\to\infty}\left(1+\frac{1}{x}\right)^{x}=e",
 "subsup": r"x_{1}^{2}+x_{2}^{2}",
 "combi": r"{}_{n}\mathrm{C}_{r}=\frac{n!}{r!(n-r)!}",
 "setbuilder": r"\{x\,|\,x^{2}<4\}",
 "nested": r"\sqrt{1+\sqrt{1+\sqrt{x}}}",
 "dfrac": r"\dfrac{\dfrac{1}{a}+\dfrac{1}{b}}{a+b}",
 "logic": r"p\Rightarrow q \iff \neg q\Rightarrow\neg p",
 "inf": r"\sum_{n=1}^{\infty}\frac{1}{n^{2}}=\frac{\pi^{2}}{6}",
 "aligned": r"\begin{aligned}x+y&=3\\x-y&=1\end{aligned}",
})
