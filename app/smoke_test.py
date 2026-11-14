r"""설치 확인용: GUI 없이 인식 → 변환 → 클립보드까지 한 번 실행해 본다.
사용: .venv\Scripts\python smoke_test.py 이미지.png
"""
import sys, time
from PIL import Image
from recognizer import Recognizer, strip_math
from latex2hwp import latex_to_hwp
from hwp_clipboard import set_equation_clipboard

r = Recognizer(); t = time.time(); r.load_async(); r.ready.wait()
if r.error:
    raise SystemExit(f"모델 로드 실패: {r.error}")
print(f"모델 로드 {time.time()-t:.1f}초")
t = time.time(); latex = strip_math(r.recognize(Image.open(sys.argv[1])))
script = latex_to_hwp(latex)
print(f"인식 {time.time()-t:.1f}초\nLaTeX: {latex}\n한글: {script}")
set_equation_clipboard(script, plain_text=latex)
print("클립보드에 넣었습니다. 한글에서 Ctrl+V 해 보세요.")
