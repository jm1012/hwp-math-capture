"""합성 문제 이미지로 지문 인식 평가 (app 의 인식기를 그대로 사용).
사용: python make_imgs.py → python evaluate.py
지표: 한글 글자 오류율(편집 거리), 수식 정답 수(표기 차이 무시), 줄 수
"""
import json, os, re, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "app"))
from PIL import Image
from recognizer import Recognizer
from passage import to_markdown


def lev(a, b):
    p = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        c = [i]
        for j, cb in enumerate(b, 1):
            c.append(min(p[j] + 1, c[j - 1] + 1, p[j - 1] + (ca != cb)))
        p = c
    return p[-1]


def norm_math(s):
    s = re.sub(r"\\(left|right|displaystyle|,|;|!|quad)", "", s)
    s = re.sub(r"\\operatorname\{(\w+)\}", r"\\\1", s)
    s = re.sub(r"\\mathrm\{(\w+)\}", r"\1", s)
    s = s.replace("\\dfrac", "\\frac").replace("\\limits", "")
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"\{(\w)\}", r"\1", s)
    return s


def parts(s):
    return re.sub(r"\$(.+?)\$", "", s), re.findall(r"\$(.+?)\$", s)


if __name__ == "__main__":
    gt = json.load(open("gt.json", encoding="utf-8"))
    r = Recognizer(); r.load_async(); r.ready.wait()
    he = hn = mo = mn = 0; tt = 0
    for name, lines in gt.items():
        t = time.time(); pred = to_markdown(r.read_passage(Image.open("imgs/" + name))); tt += time.time() - t
        g = " ".join(lines)
        gtext, gm = parts(g); ptext, pm = parts(pred)
        gh = "".join(re.findall(r"[가-힣]", gtext)); ph = "".join(re.findall(r"[가-힣]", ptext))
        e = lev(gh, ph); he += e; hn += len(gh)
        pmn = [norm_math(x) for x in pm]; ok = 0
        for x in gm:
            if norm_math(x) in pmn:
                pmn.remove(norm_math(x)); ok += 1
        mo += ok; mn += len(gm)
        print(name, e, f"{ok}/{len(gm)}", "|", pred.replace("\n", " ⏎ "))
    print(f"\n한글 글자 오류율 {he}/{hn} = {he/hn:.1%}, 수식 정답 {mo}/{mn} = {mo/mn:.1%}, 평균 {tt/len(gt):.2f}초")
