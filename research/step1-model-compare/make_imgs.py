import json, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
F = {
 "frac": r"\frac{a+b}{c-d}",
 "quadratic": r"x=\frac{-b\pm\sqrt{b^{2}-4ac}}{2a}",
 "pythag": r"a^{2}+b^{2}=c^{2}",
 "sum": r"\sum_{k=1}^{n}k=\frac{n(n+1)}{2}",
 "integral": r"\int_{0}^{1}x^{2}\,dx=\frac{1}{3}",
 "limit": r"\lim_{x\to0}\frac{\sin x}{x}=1",
 "deriv": r"f'(x)=\lim_{h\to0}\frac{f(x+h)-f(x)}{h}",
 "log": r"\log_{a}xy=\log_{a}x+\log_{a}y",
 "trig": r"\sin^{2}\theta+\cos^{2}\theta=1",
 "nthroot": r"\sqrt[3]{x^{2}+1}",
 "euler": r"e^{i\pi}+1=0",
 "binom": r"(a+b)^{n}=\sum_{k=0}^{n}\binom{n}{k}a^{k}b^{n-k}",
 "ineq": r"|x-3|\leq 2",
 "vector": r"\vec{a}\cdot\vec{b}=|\vec{a}||\vec{b}|\cos\theta",
 "seq": r"a_{n}=a_{1}r^{n-1}",
 "set": r"A\cap B=\{x\mid x\in A,\ x\in B\}",
}
fonts = {"cm": "cm", "stix": "stix", "dv": "dejavusans"}
meta = {}
for name, tex in F.items():
    for fk, fs in fonts.items():
        plt.rcParams["mathtext.fontset"] = fs
        fig = plt.figure(figsize=(0.01, 0.01))
        fig.text(0, 0, f"${tex}$", fontsize=22)
        p = f"/home/user/step1/imgs/{name}_{fk}.png"
        fig.savefig(p, dpi=150, bbox_inches="tight", pad_inches=0.15, facecolor="white")
        plt.close(fig)
        meta[f"{name}_{fk}"] = tex
json.dump(meta, open("/home/user/step1/imgs/truth.json", "w"), ensure_ascii=False, indent=1)
print(len(meta))
