import json, os, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
from problems import PROBLEMS
import sys
FONT_DIR = sys.argv[1] if len(sys.argv) > 1 else "/usr/share/fonts/truetype/nanum"  # 나눔명조, 나눔고딕
FONTS = {"myeongjo": (FONT_DIR + "/NanumMyeongjo.ttf", "cm"),
         "gothic": (FONT_DIR + "/NanumGothic.ttf", "stix")}
os.makedirs("imgs", exist_ok=True)
gt = {}
for fname, (path, mfs) in FONTS.items():
    fm.fontManager.addfont(path)
    family = fm.FontProperties(fname=path).get_name()
    plt.rcParams.update({"font.family": family, "mathtext.fontset": mfs, "axes.unicode_minus": False})
    for i, lines in enumerate(PROBLEMS, 1):
        h = 0.45 * len(lines) + 0.2
        fig = plt.figure(figsize=(7.5, h), dpi=150)
        for j, ln in enumerate(lines):
            fig.text(0.02, 1 - (j + 0.75) / (len(lines) + 0.45), ln, fontsize=14, va="center")
        name = f"p{i:02d}_{fname}.png"
        fig.savefig("imgs/" + name, bbox_inches="tight", pad_inches=0.15, facecolor="white")
        plt.close(fig)
        gt[name] = lines
json.dump(gt, open("gt.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(len(gt))
