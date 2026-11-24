"""시험 기준: exe 와 같은 파이썬 코드(onnxruntime 원본)로 184장을 읽어 JSON 으로 저장.

    python web/test/native_run.py 결과.json [이름 일부,...]
웹 버전 결과(web_run.mjs)와 compare.py 로 비교한다. app/model 에 모델이 있어야 함.
"""
import glob, json, os, sys, time
APP = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "app")
sys.path.insert(0, APP)
from PIL import Image
from latex2hwp import latex_to_hwp
from passage import to_markdown
from recognizer import Recognizer

files = sorted(glob.glob(os.environ.get("TESTSET", "/mnt/project-files/test-set") + "/20*/*.png"))
if len(sys.argv) > 2:
    files = [f for f in files if any(k in f for k in sys.argv[2].split(","))]
rec = Recognizer(); rec._load()
if rec.error:
    raise rec.error
res = {}
for i, f in enumerate(files, 1):
    name = os.path.splitext(os.path.basename(f))[0]
    t0 = time.time()
    with Image.open(f) as im:
        paras = rec.read_passage(im.convert("RGB"))
    def hw(v):
        try:
            return latex_to_hwp(v)
        except Exception as e:
            return f"[변환 실패 {e}]"
    hwp = [[(k, v if k == "text" else ("[img]" if k == "image" else hw(v))) for k, v in p] for p in paras]
    res[name] = {"hwp": hwp, "md": to_markdown(paras), "sec": round(time.time() - t0, 2)}
    print(i, name, res[name]["sec"], flush=True)
json.dump(res, open(sys.argv[1], "w"), ensure_ascii=False, default=lambda o: "[img]", indent=0)
