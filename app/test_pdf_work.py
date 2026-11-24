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



def test_pdf_spacing():
    """PDF 글자 정보(공백 글자 포함)의 띄어쓰기로 인식 결과의 한글 사이 공백을 맞춤"""
    def chars(text, y=100):
        out, x = [], 10.0
        for c in text:
            w = 4.0 if c == " " else 10.0
            out.append(([x, y, x + w, y + 12], c))
            x += w
        return out
    ch = chars("15. 첫째항이 자연수인 수열 \ue000이 있다.") + [(None, "\r"), (None, "\n")] + chars("이산확률변수 \ue001를", 120)
    paras = [[("text", "첫째 항이자연수인 수열 "), ("math", "a_n"), ("text", "이 있다.")],
             [("text", "이 산확률변수 "), ("math", "X"), ("text", "를")]]
    got = W.pdf_spacing(ch, [L.Block([0, 90, 900, 140])], paras)
    assert got == [[("text", "첫째항이 자연수인 수열 "), ("math", "a_n"), ("text", "이 있다.")],
                   [("text", "이산확률변수 "), ("math", "X"), ("text", "를")]], got
    # 문제 상자 밖 글자는 쓰지 않음, 글자 정보가 없으면 그대로
    assert W.pdf_spacing(ch, [L.Block([0, 0, 900, 50])], paras) == paras
    assert W.pdf_spacing([], [L.Block([0, 90, 900, 140])], paras) == paras


def test_spacer_fixes():
    from spacing import Spacer, fix_terms, respace_paragraph
    assert fix_terms("첫째 항이자 연수인 수열") == "첫째항이 자연수인 수열"   # 용어 속 공백은 용어 앞으로
    assert fix_terms("이 산확률변수") == "이산확률변수"
    sp = Spacer()
    # 여러 줄 수식 뒤 조사로 시작하는 문단: 앞 수식을 문맥으로
    assert respace_paragraph(sp, [("text", "가실수 전체의 집합에서 연속일 때")], after_math=True)[0][1].startswith("가 실수")

if __name__ == "__main__":
    test_roundtrip()
    test_flags()
    test_pdf_spacing()
    test_spacer_fixes()
    print("ok")
