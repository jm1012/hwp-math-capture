import json, time, re, sys, difflib
from pathlib import Path
from PIL import Image
D = Path("/home/user/step1/imgs"); truth = json.load(open(D/"truth.json"))

def norm(s):
    s = s.strip().strip("$")
    s = re.sub(r"\\(left|right|displaystyle|mathrm|operatorname)\b", "", s)
    s = re.sub(r"\\[,;!: ]|\\quad|\\qquad", "", s)
    s = s.replace("\\le ", "\\leq ").replace("\\le{", "\\leq{")
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"\{([A-Za-z0-9])\}", r"\1", s)   # {a} -> a
    return s

def score(pred, gt):
    a, b = norm(pred), norm(gt)
    return (a == b), difflib.SequenceMatcher(None, a, b).ratio()

def load(name):
    if name == "pix2tex":
        from pix2tex.cli import LatexOCR
        m = LatexOCR(); return lambda im: m(im)
    if name == "texify":
        from transformers import PretrainedConfig
        PretrainedConfig.__repr__ = lambda self: self.__class__.__name__
        from texify.inference import batch_inference
        from texify.model.model import load_model
        from texify.model.processor import load_processor
        mo, pr = load_model(), load_processor()
        return lambda im: batch_inference([im], mo, pr)[0]
    if name == "p2t":
        from transformers import TrOCRProcessor
        from optimum.onnxruntime import ORTModelForVision2Seq
        rid = "breezedeus/pix2text-mfr-1.5"
        pr = TrOCRProcessor.from_pretrained(rid); mo = ORTModelForVision2Seq.from_pretrained(rid, use_cache=False)
        def f(im):
            pv = pr(images=[im], return_tensors="pt").pixel_values
            return pr.batch_decode(mo.generate(pv, max_new_tokens=256), skip_special_tokens=True)[0]
        return f

name = sys.argv[1]
t0 = time.time(); f = load(name); load_t = time.time() - t0
rows = []
for k, gt in truth.items():
    im = Image.open(D/f"{k}.png").convert("RGB")
    t = time.time(); p = f(im); dt = time.time() - t
    ex, sim = score(p, gt)
    rows.append(dict(id=k, gt=gt, pred=p, exact=ex, sim=round(sim, 3), sec=round(dt, 2)))
json.dump(dict(model=name, load_sec=round(load_t,1), rows=rows), open(f"/home/user/step1/res_{name}.json", "w"), ensure_ascii=False, indent=1)
n = len(rows)
print(name, "exact", sum(r["exact"] for r in rows), "/", n, "avg_sim", round(sum(r["sim"] for r in rows)/n, 3), "avg_sec", round(sum(r["sec"] for r in rows)/n, 2), "load", round(load_t,1))
