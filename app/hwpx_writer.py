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
        kw = dict(separator_type="SOLID", separator_width_mm=0.12, separator_color="#000000") if col_line else {}
        d.page.set_columns(cols, same_gap=round(col_gap_pt * PT), **kw)
    col_w = (page_w_pt * PT - l - r - (cols - 1) * col_gap_pt * PT) / cols

    n_eq = n_pic = n_par = 0
    body_cp = None
    first = True
    for it in items:
        paras = it["paras"] or [[("text", "")]]
        for pi, segs in enumerate(paras):
            p = d.add_paragraph("", include_run=False) if not first else d.paragraphs[0]
            first = False
            n_par += 1
            if pi == 0:
                if it.get("col_break"):
                    p.column_break = True
                if it.get("space_pt"):
                    p.spacing_before_pt = round(float(it["space_pt"]), 1)
            if segs and all(k == "pic" for k, _ in segs):
                p.alignment = "CENTER"
            for k, v in segs:
                if k == "text":
                    if not v:
                        continue
                    if body_cp is None:
                        run = p.add_run(v, size=body_pt)
                        body_cp = _charpr(run)
                    else:
                        p.add_run(v, char_pr_id_ref=body_cp)
                elif k == "eq":
                    try:
                        p.add_equation(v, font_size=body_pt, font=eq_font, char_pr_id_ref=body_cp)
                    except Exception:  # noqa: BLE001  한글이 못 그릴 스크립트(괄호 짝 등): 글자로 남겨 둠
                        p.add_run(v, char_pr_id_ref=body_cp)
                        continue
                    n_eq += 1
                elif k == "pic":
                    png, w, h, _pw, _ph = v
                    if w > col_w:
                        w, h = col_w, h * col_w / w
                    item = d.media.add_image(png, "png")
                    p.add_picture(item, width=max(1, round(w)), height=max(1, round(h)), char_pr_id_ref=body_cp)
                    n_pic += 1
            if not p.runs:
                p.add_run("", char_pr_id_ref=body_cp)
    buf = io.BytesIO()
    d.save(buf)
    with open(path, "wb") as f:
        f.write(buf.getvalue())
    return {"paragraphs": n_par, "equations": n_eq, "pictures": n_pic}
