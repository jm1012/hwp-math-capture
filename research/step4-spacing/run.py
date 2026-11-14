"""앱의 띄어쓰기 교정기(app/spacing.py) 평가. 사용: python run.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "app"))
from spacing import Spacer
from ev import score
sp = Spacer()
f = lambda s, keep: sp.space(s)
print("공백 모두 지움:", score(f, False))
print("공백 절반 지움:", score(f, True))
