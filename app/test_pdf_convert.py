"""v2.0.6 PDF → .hwpx 부품 시험 (모델 없이 도는 것만).  python test_pdf_convert.py"""
import io
import os
import re
import tempfile
import zipfile

import numpy as np
from PIL import Image, ImageDraw

import pdf_layout as L
from hwpx_writer import write_hwpx
from pdf_convert import _put_number, parse_pages


def test_parse_pages():
    assert parse_pages("", 5) == [0, 1, 2, 3, 4]
    assert parse_pages("1-3,5", 10) == [0, 1, 2, 4]
    assert parse_pages("8-", 10) == [7, 8, 9]
    assert parse_pages("0-2, 30", 5) == [0, 1]


def test_columns_with_divider():
    img = Image.new("L", (1000, 1400), 255)
    d = ImageDraw.Draw(img)
    d.line((500, 200, 500, 1300), fill=0, width=3)  # 단 경계선
    for y in (250, 300, 700):
        d.rectangle((80, y, 420, y + 20), fill=0)
        d.rectangle((580, y, 920, y + 20), fill=0)
    cols, top, bot = L.find_columns(np.asarray(img) < 160)
    assert len(cols) == 2 and cols[0][1] < 500 < cols[1][0]
    assert 190 <= top <= 205 and 1295 <= bot <= 1305


def test_columns_by_gap():
    img = Image.new("L", (1000, 1400), 255)
    d = ImageDraw.Draw(img)
    for y in range(200, 1200, 60):
        d.rectangle((80, y, 440, y + 20), fill=0)
        d.rectangle((560, y, 920, y + 20), fill=0)
    cols, _, _ = L.find_columns(np.asarray(img) < 160)
    assert len(cols) == 2 and cols[0][1] <= 560 and cols[1][0] >= 440


def test_group_words():
    # "1" 과 "." 사이가 조금 떨어져도 한 단어, 글자 순서가 뒤섞여 들어와도 위치대로
    chars = [([30, 26, 34, 30], "."), ([10, 10, 22, 30], "1"), ([60, 10, 80, 30], "함"), ([82, 10, 102, 30], "수")]
    ws = L.group_words(chars)
    assert sorted(w["val"] for w in ws) == sorted(["1", ".", "함수"])
    starts = L._num_starts(ws, 0, 500, 0, 100, 20)
    assert [s[1] for s in starts] == [1]


def test_put_number():
    assert _put_number([[("text", "함수 "), ("eq", "x")]], 3, True)[0][0] == ("text", "3. 함수 ")
    # 번호를 못 지워 인식된 번호가 남은 경우
    assert _put_number([[("eq", "bold 6"), ("text", ", 9개의")]], 6, False)[0][0] == ("text", "6. 9개의")
    assert _put_number([[("text", "12. 다음")]], 12, False)[0][0] == ("text", "12. 다음")


def test_write_hwpx():
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(buf, "PNG")
    items = [{"paras": [[("text", "1. 함수 "), ("eq", "f(x)=x^2"), ("text", " 에 대하여")],
                        [("pic", (buf.getvalue(), 6000, 4500, 40, 30))]], "col_break": False, "space_pt": 0},
             {"paras": [[("text", "2. 다음 "), ("eq", "{1} over {2}")]], "col_break": True, "space_pt": 30}]
    with tempfile.TemporaryDirectory() as t:
        p = os.path.join(t, "a.hwpx")
        n = write_hwpx(p, items, page_w_pt=842, page_h_pt=1191, cols=2, body_pt=10.5)
        assert n == {"paragraphs": 3, "equations": 2, "pictures": 1}
        z = zipfile.ZipFile(p)
        s = z.read("Contents/section0.xml").decode("utf-8")
        assert 'colCount="2"' in s and 'columnBreak="1"' in s
        assert re.findall(r"<hp:script>(.*?)</hp:script>", s) == ["f(x)=x^2", "{1} over {2}"]
        assert any(n.startswith("BinData/") for n in z.namelist())
        assert 'right="3000" top="0" bottom="2250"' in s and 'dimwidth="3000"' in s  # 40×30 픽셀 × 75
        # 앞 문단의 여백·정렬이 다음 문단으로 번지지 않음 (문단 모양 번호가 서로 달라야 함)
        refs = re.findall(r'<hp:p [^>]*paraPrIDRef="(\d+)"', s)
        assert refs[1] != refs[2] and refs[0] != refs[2]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
