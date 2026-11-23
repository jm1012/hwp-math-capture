"""작업 파일 저장·불러오기, 의심 표시 (인식 모델 없이). python test_pdf_work.py"""
import os
import tempfile

from PIL import Image

import pdf_layout as L
import pdf_work as W
from passage import Figure


def _work(d):
    fig = Figure(Image.new("RGB", (40, 30), "white"), "image", 1.0)
    fig.em = 12.0
    probs = [L.Problem(1, 0, 0, [L.Block([10, 10, 200, 80], "가")], num_box=[10, 10, 20, 20]),
             L.Problem(None, 0, 1, [L.Block([300, 10, 500, 60], "")], kind="notice")]
    info = {"cols": [(0, 250), (260, 520)], "top": 5, "bot": 700, "lh": 20.0, "page": 0, "size": (520, 740), "text": True}
    results = [[[("text", "함수 "), ("math", "f(x)=x^{2}")], [("image", fig)]], None]
    return W.Work(dir=d, pdf="x.pdf", out=os.path.join(d, "x.hwpx"), dpi=150, page_info=[info], probs=probs,
                  pinfo=[0, 0], results=results, ems=[20.0], flags=[["수식 속에 한글"], []], edited=[False, False])


def test_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        wd = os.path.join(d, "x_작업")
        w = _work(wd)
        W.save(w, {0: Image.new("RGB", (50, 50), "white")})
        v = W.load(wd)
        assert v.probs[0].num == 1 and v.probs[0].num_box == [10, 10, 20, 20] and v.probs[1].kind == "notice"
        assert v.results[0][0] == [("text", "함수 "), ("math", "f(x)=x^{2}")]
        f = v.results[0][1][0][1]
        assert isinstance(f, Figure) and f.img.size == (40, 30) and f.em == 12.0
        assert v.results[1] is None and v.page_info[0]["cols"] == [(0, 250), (260, 520)]
        assert v.label(0) == "1쪽 1번" and v.label(1) == "1쪽 안내"
        assert os.path.exists(W.crop_path(v, 0))
        assert "1. 함수 〔" in W.preview_text(v.results[0], 1)
    print("ok test_roundtrip")


def test_flags():
    assert W.problem_flags([[("text", "① "), ("math", "1"), ("text", " ③ "), ("math", "2")]]) == ["선지 번호 차례가 이상함"]
    assert "수식 속에 한글" in W.problem_flags([[("math", "x 인 상수")]])
    assert "수식 괄호 짝이 안 맞음" in W.problem_flags([[("math", "\\frac{1}{2")]])
    assert W.problem_flags([[("text", "")]]) == ["인식된 내용 없음"]
    assert W.problem_flags([[("text", "가")]], missing=4) == ["원본보다 한글이 4자 적음"]
    assert W.problem_flags([[("text", "함수 "), ("math", "\\left( x \\right)")]], ["지어낸 수식을 글자로 바꿈"]) == \
        ["지어낸 수식을 글자로 바꿈"]
    words = [{"val": "함수가", "box": [0, 0, 30, 10]}, {"val": "밖", "box": [100, 100, 110, 110]}]
    assert W.hangul_missing(words, [L.Block([0, 0, 50, 20])], [[("text", "함수")]]) == 1
    print("ok test_flags")


if __name__ == "__main__":
    test_roundtrip()
    test_flags()
