r"""설치 확인용: GUI 없이 인식 → 변환 → 클립보드까지 한 번 실행해 본다.
사용: .venv\Scripts\python smoke_test.py 이미지.png            (수식 하나)
      .venv\Scripts\python smoke_test.py --passage 이미지.png  (글자+수식 지문)
"""
import sys, time
from PIL import Image
from recognizer import Recognizer
from latex2hwp import latex_to_hwp
from hwp_clipboard import set_equation_clipboard, set_passage_clipboard

passage = "--passage" in sys.argv
path = [a for a in sys.argv[1:] if not a.startswith("--")][0]
r = Recognizer(); t = time.time(); r.load_async(); r.ready.wait()
if r.error:
    raise SystemExit(f"모델 로드 실패: {r.error}")
print(f"모델 로드 {time.time()-t:.1f}초")
t = time.time()
if passage:
    from passage import to_markdown
    paras = r.read_passage(Image.open(path))
    hwp = [[(k, v) if k == "text" else ("eq", latex_to_hwp(v)) for k, v in p] for p in paras]
    print(f"인식 {time.time()-t:.1f}초, 문단 {len(paras)}개")
    for p in hwp:
        print("  ¶", "".join(v if k == "text" else f"[{v}]" for k, v in p))
    set_passage_clipboard(hwp, plain_text=to_markdown(paras))
else:
    latex = r.recognize(Image.open(path))
    script = latex_to_hwp(latex)
    print(f"인식 {time.time()-t:.1f}초\nLaTeX: {latex}\n한글: {script}")
    set_equation_clipboard(script, plain_text=latex)
print("클립보드에 넣었습니다. 한글에서 Ctrl+V 해 보세요.")
