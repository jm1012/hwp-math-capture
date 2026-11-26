"""읽지 않은 곳 점검(passage.unread_ink)과 선지 모양 점검(pdf_work._choices_mixed) 시험 (모델 없이)"""
import numpy as np
from PIL import Image, ImageDraw

from passage import unread_ink
from pdf_work import _choices_mixed

LH = 30


def canvas():
    im = Image.new("L", (600, 300), 255)
    return im, ImageDraw.Draw(im)


def test_minus_outside_formula_box():
    im, d = canvas()
    d.rectangle([100, 100, 115, 102], fill=0)        # 상자 밖 마이너스
    d.text((130, 90), "1/4", fill=0)                 # 수식 (상자 안)
    out = unread_ink(np.asarray(im), [[125, 85, 170, 115]], LH)
    assert len(out) == 1 and out[0][0] <= 100 <= out[0][2]


def test_ignored_shapes():
    im, d = canvas()
    d.ellipse([20, 20, 46, 46], outline=0, width=2)   # 동그라미 (선지 번호)
    d.line([32, 26, 32, 40], fill=0, width=2)        # 안의 숫자
    d.rectangle([60, 60, 500, 140], outline=0, width=2)  # 조건 상자 테두리
    d.line([60, 200, 400, 200], fill=0, width=1)     # 밑줄
    d.point([(300, 250), (301, 250), (300, 251)], fill=0)  # 점
    assert unread_ink(np.asarray(im), [], LH) == []


def test_glyph_pieces_merged():
    im, d = canvas()
    d.line([200, 100, 200, 112], fill=0, width=2)    # 'ㄴ'
    d.line([200, 112, 215, 112], fill=0, width=2)
    d.line([196, 120, 220, 120], fill=0, width=2)    # 'ㅡ'
    out = unread_ink(np.asarray(im), [], LH)
    assert len(out) == 1


def test_choices_mixed():
    segs = [("text", "① "), ("math", "-\\frac{1}{2}"), ("text", " ② "), ("math", "\\frac{1}{4}"),
            ("text", " ③ 1|4 ④ "), ("math", "\\frac{3}{4}"), ("text", " ⑤ "), ("math", "1")]
    assert _choices_mixed(segs)
    ok = [("text", "① "), ("math", "1"), ("text", " ② "), ("math", "2"), ("text", " ③ "), ("math", "3")]
    assert not _choices_mixed(ok)
    words = [("text", "① 참 ② 거짓 ③ "), ("math", "x"), ("text", " ④ "), ("math", "y")]
    assert not _choices_mixed(words)
