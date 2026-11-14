from latex2hwp import latex_to_hwp
from cases import CASES
for k, v in CASES.items():
    print(f"{k:12} {v}\n{'':12} {latex_to_hwp(v)}")
