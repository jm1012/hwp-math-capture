"""인식 결과 → 한글 문서(.hwpx) 파일. 한글 없이 만든다 (python-hwpx, Apache-2.0).

J PC 한글 2020(11.0.0.1623)에서 확인 (2026-11-23): 2단·구분선, 단 나누기, 쪽 나누기, 수식(HYhwpEQ/HancomEQN), 그림 정상.
한글 2020은 열 때 수식 상자 크기를 다시 계산하지 않으므로 수식 크기는 python-hwpx 의 측정값을 넣는다.

문서 구조 (convert 가 만듦):
  items = [{"paras": [[("text", "글자"), ("eq", 한글 수식 스크립트), ("pic", (PNG, 가로, 세로 HWPUNIT, 픽셀 가로, 세로))], …],
            "col_break": 이 문제 앞에서 단 나누기, "space_pt": 앞 여백(pt)}, …]
"""
from __future__ import annotations

import io

PT = 100  # HWPUNIT per pt
MM = 7200 / 25.4


def _charpr(run):
    for k in ("char_pr_id_ref", "charPrIDRef"):
        v = getattr(run, k, None)
        if v is not None:
            return v
    return run.element.get("charPrIDRef")


def _fix_picture_clip(pic, px_w: int, px_h: int):
    """그림 자르기 범위(imgClip)와 원본 크기(imgDim)는 '원본 그림' 단위(픽셀 × 75, 96dpi 기준)여야 한다.
    python-hwpx 는 문서에 보일 크기를 넣어서, 한글 2020이 그림을 원래 크기로 그리고 보일 크기만큼만 잘라 보여 줌
    (큰 그림의 왼쪽 위만 보임, J PC 2026-11-23). 한글이 그림을 복사할 때 쓰는 값과 같게 고친다."""
    el = getattr(pic, "element", pic)
    W, H = str(int(px_w) * 75), str(int(px_h) * 75)
    for c in el.iter():
        tag = c.tag.split("}")[-1]
        if tag == "imgClip":
            c.set("left", "0"); c.set("top", "0"); c.set("right", W); c.set("bottom", H)
        elif tag == "imgDim":
            c.set("dimwidth", W); c.set("dimheight", H)


_HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def _float_at_paper(el, x, y, wrap):
    """그림·선·표를 쪽(종이) 기준 자리에 고정"""
    el.set("textWrap", wrap)
    pos = el.find(_HP + "pos")
    for k, v in (("treatAsChar", "0"), ("vertRelTo", "PAPER"), ("horzRelTo", "PAPER"), ("vertAlign", "TOP"),
                 ("horzAlign", "LEFT"), ("vertOffset", str(round(y))), ("horzOffset", str(round(x))),
                 ("flowWithText", "0")):
        pos.set(k, v)


def _master_lines(d, xs, y0, y1):
    """모든 쪽에 나오는 바탕쪽에 세로선 (x, HWPUNIT)"""
    mp = d.parts.add_master_page(text="", page_type="BOTH", section=0)
    para = mp.paragraphs[0]
    for x in xs:
        ln = para.add_line(0, 0, 0, y1 - y0, line_color="#000000", line_width_mm=0.12, treat_as_char=False)
        _float_at_paper(ln.element, x, y0, "BEHIND_TEXT")
        ln.element.find(_HP + "pos").set("allowOverlap", "1")


def _text_w(s, em):
    w = 0.0
    for c in s:
        w += 0.3 if c.isspace() else 1.0 if ord(c) >= 0x2E80 else 0.55
    return w * em


def seg_width(segs, body_pt):
    """글자·수식 조각들의 대략 폭 (HWPUNIT). 수식은 python-hwpx 측정값(한글이 그릴 크기)"""
    from hwpx.equation.measure import measure_equation
    em = body_pt * PT
    w = 0.0
    for k, v in segs:
        if k == "text":
            w += _text_w(v, em)
        elif k == "eq":
            try:
                w += measure_equation(v, base_unit=round(em)).width
            except Exception:  # noqa: BLE001
                w += _text_w(v, em)
        elif k == "pic":
            w += v[1]
    return w


def layout_choices(items, col_w, body_pt):
    """선지 배치: 다 들어가면 한 줄, 아니면 반씩 두 줄(5개면 3개+2개), 그래도 길면 한 줄에 하나.
    선지 사이는 탭(같은 간격의 탭 자리)으로 띄움. 결과: (줄마다 segs, 탭 자리 HWPUNIT 목록 또는 None)"""
    n = len(items)
    widest = max(seg_width(it, body_pt) for it in items) + 1.5 * body_pt * PT  # 선지 사이 최소 1.5글자
    for per in (n, (n + 1) // 2, 1):
        if per == 1 or widest <= col_w / per:
            break
    cell = col_w / per
    rows = []
    for i in range(0, n, per):
        row = []
        for j, it in enumerate(items[i:i + per]):
            if j:
                row.append(("tab", ""))
            row += it
        rows.append(row)
    return rows, ([round(cell * k) for k in range(1, per)] or None)


def _add_notice(d, anchor, it, body_pt):
    """안내 상자(확인 사항 등): 원본과 같은 쪽 자리에 떠 있는 1칸 표. 글은 표 둘레로 비켜 감"""
    x, y, w, h = (v * PT for v in it["box_pt"])
    t = anchor.add_table(1, 1, width=round(w), height=round(h))
    _float_at_paper(t.element, x, y, "TOP_AND_BOTTOM")
    t.set_cell_text(0, 0, "\n".join(it["lines"]))


def write_hwpx(path: str, items, *, page_w_pt: float, page_h_pt: float, margins_pt=(42, 42, 42, 42),
               cols: int = 2, col_gap_pt: float = 24, col_line: bool = True, body_pt: float = 10.0,
               eq_font: str = "HYhwpEQ") -> dict:
    """items 를 .hwpx 로 저장. margins_pt = (왼쪽, 오른쪽, 위, 아래). 결과: 개수 요약"""
    from hwpx import HwpxDocument

    d = HwpxDocument.new()
    landscape = page_w_pt > page_h_pt
    d.page.set_size(width=round(page_w_pt * PT), height=round(page_h_pt * PT),
                    orientation="NARROWLY" if landscape else "WIDELY")
    l, r, t, b = (round(v * PT) for v in margins_pt)
    d.page.set_margins(left=l, right=r, top=t, bottom=b, header=0, footer=0)
    if cols > 1:
        d.page.set_columns(cols, same_gap=round(col_gap_pt * PT))
    col_w = (page_w_pt * PT - l - r - (cols - 1) * col_gap_pt * PT) / cols
    if cols > 1 and col_line:
        # 단 구분선: 한글의 단 구분선은 그 쪽 글이 있는 높이까지만 그어짐 → 바탕쪽에 본문 위~아래 세로선
        _master_lines(d, [l + (i + 1) * col_w + (i + 0.5) * col_gap_pt * PT for i in range(cols - 1)],
                      t, round(page_h_pt * PT) - b)

    base_pp = d.paragraphs[0].element.get("paraPrIDRef", "0")
    n = {"eq": 0, "pic": 0, "par": 0}
    st = {"body_cp": None, "first": True}

    def new_par():
        # 문단 모양은 늘 기본(0번)에서 시작: add_paragraph 는 앞 문단의 모양(여백·가운데 정렬)을 물려받음
        p = d.add_paragraph("", include_run=False, para_pr_id_ref=base_pp, inherit_style=False) \
            if not st["first"] else d.paragraphs[0]
        st["first"] = False
        n["par"] += 1
        return p

    def emit(p, segs):
        for k, v in segs:
            if k == "text":
                if not v:
                    continue
                if st["body_cp"] is None:
                    run = p.add_run(v, size=body_pt)
                    st["body_cp"] = _charpr(run)
                else:
                    p.add_run(v, char_pr_id_ref=st["body_cp"])
            elif k == "tab":
                p.add_run("\t", char_pr_id_ref=st["body_cp"])
            elif k == "eq":
                try:
                    p.add_equation(v, font_size=body_pt, font=eq_font, char_pr_id_ref=st["body_cp"])
                except Exception:  # noqa: BLE001  한글이 못 그릴 스크립트(괄호 짝 등): 글자로 남겨 둠
                    p.add_run(v, char_pr_id_ref=st["body_cp"])
                    continue
                n["eq"] += 1
            elif k == "pic":
                png, w, h, _pw, _ph = v
                if w > col_w:
                    w, h = col_w, h * col_w / w
                item = d.media.add_image(png, "png")
                pic = p.add_picture(item, width=max(1, round(w)), height=max(1, round(h)), char_pr_id_ref=st["body_cp"])
                _fix_picture_clip(pic, _pw, _ph)
                n["pic"] += 1

    last_p = None
    for it in items:
        if it.get("notice"):
            if last_p is None:
                last_p = new_par()
            _add_notice(d, last_p, it, body_pt)
            continue
        paras = it["paras"] or [[("text", "")]]
        for pi, segs in enumerate(paras):
            rows = [segs]
            tabs = None
            if len(segs) == 1 and segs[0][0] == "choices":
                rows, tabs = layout_choices(segs[0][1], col_w, body_pt)
            for ri, row in enumerate(rows):
                p = new_par()
                last_p = p
                if pi == 0 and ri == 0:
                    if it.get("col_break"):
                        p.column_break = True
                    if it.get("space_pt"):
                        p.spacing_before_pt = round(float(it["space_pt"]), 1)
                if tabs:
                    d.styles.apply_paragraph_format(paragraph=p, tab_stops=[{"pos_mm": t / MM, "type": "LEFT"} for t in tabs])
                elif row and (all(k == "pic" for k, _ in row) or (len(row) == 1 and row[0][0] == "eq")):
                    p.alignment = "CENTER"  # 그림만, 또는 수식 하나만 있는 줄(따로 쓴 식)은 가운데
                emit(p, row)
                if not p.runs:
                    p.add_run("", char_pr_id_ref=st["body_cp"])
    buf = io.BytesIO()
    d.save(buf)
    with open(path, "wb") as f:
        f.write(buf.getvalue())
    return {"paragraphs": n["par"], "equations": n["eq"], "pictures": n["pic"]}
