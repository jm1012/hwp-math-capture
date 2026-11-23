"""PDF 변환 작업 파일 (v2.0.7)

변환할 때 문제마다 자리(쪽·상자)·문제 그림·인식 결과를 "<결과 이름>_작업" 폴더에 남긴다.
나중에 문제 확인 창(review_dialog)에서
  - 의심 문제(지어낸 수식, 수식 속 한글, 괄호 짝 등)를 찾아 원본 그림과 결과를 나란히 보고
  - 영역을 다시 잡거나 해상도를 바꿔 다시 읽은 뒤
  - 그 문제만 클립보드로 복사하거나, 한글 파일을 다시 저장한다 (다시 인식하지 않으므로 몇 초).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field

from PIL import Image

import pdf_layout as L

VERSION = 1
HANGUL = re.compile(r"[가-힣]")
CIRC = "①②③④⑤⑥⑦⑧⑨⑩"


def work_dir_for(out_path: str) -> str:
    return os.path.splitext(out_path)[0] + "_작업"


@dataclass
class Work:
    dir: str
    pdf: str
    out: str
    dpi: int
    figures: bool = True
    letters: tuple | None = None
    page_info: list = field(default_factory=list)   # 쪽마다 {cols, top, bot, lh, page, size, text}
    probs: list = field(default_factory=list)       # pdf_layout.Problem
    pinfo: list = field(default_factory=list)       # 문제마다 page_info 번호
    results: list = field(default_factory=list)     # 문제마다 인식 결과 문단들 (안내 상자는 None)
    ems: list = field(default_factory=list)
    flags: list = field(default_factory=list)       # 문제마다 의심 이유 목록
    edited: list = field(default_factory=list)      # 확인 창에서 결과를 바꾼 문제
    regions: list = field(default_factory=list)     # 문제마다 영역 [{"box": 문제 그림 픽셀, "kind": math/text/image}]
    user_regions: list = field(default_factory=list)  # 사용자가 정한 영역 (있으면 다시 읽을 때 씀)

    def label(self, k: int) -> str:
        p = self.probs[k]
        if p.kind == "notice":
            return f"{p.page + 1}쪽 안내"
        return f"{p.page + 1}쪽 " + (f"{p.num}번" if p.num is not None else "(이어짐)")

    def jobs(self):
        """pdf_convert.build 에 넘길 (문제, 쪽 정보) 목록"""
        return [(p, self.page_info[i]) for p, i in zip(self.probs, self.pinfo)]


# ---------------------------------------------------------------- 의심 문제 찾기
def _balanced(latex: str) -> bool:
    s = re.sub(r"\\[{}]", "", latex)
    depth = 0
    for c in s:
        depth += (c == "{") - (c == "}")
        if depth < 0:
            return False
    if depth:
        return False
    return len(re.findall(r"\\left\b", latex)) == len(re.findall(r"\\right\b", latex))


def hangul_missing(words, blocks, paras) -> int:
    """PDF 글자 정보에 있는 한글 중 결과 글자에 없는 수 (글자 정보가 있는 PDF 만).
    글자 정보 쪽에 없는 글자(그려진 글자 등)는 셀 수 없으므로 '빠진 것'만 센다."""
    from collections import Counter

    def frac(w, b):
        x0, y0, x1, y1 = w["box"]
        ix = max(0, min(x1, b[2]) - max(x0, b[0]))
        iy = max(0, min(y1, b[3]) - max(y0, b[1]))
        return ix * iy / max(1e-6, (x1 - x0) * (y1 - y0))

    gw = [w["val"] for w in words if sum(frac(w, b.box) for b in blocks) > 0.5]
    g = Counter(HANGUL.findall(" ".join(gw)))
    o = Counter(HANGUL.findall(" ".join(v for para in paras for k, v in para if k == "text")))
    return sum((g - o).values())


def problem_flags(paras, notes=(), crop_size=None, missing=0) -> list:
    """인식 결과에서 사람이 봐야 할 만한 곳 (특정 문제에 맞춘 규칙이 아니라 결과 모양만 봄).
    crop_size: 문제 그림 크기 (그림이 문제 대부분을 차지하는지 볼 때). missing: hangul_missing 값"""
    out = list(dict.fromkeys(notes))
    if paras is None:
        return out
    if missing >= 3:
        out.append(f"원본보다 한글이 {missing}자 적음")
    segs = [s for para in paras for s in para]
    if crop_size:
        area = sum(v.img.width * v.img.height for k, v in segs if k == "image")
        if area > 0.6 * crop_size[0] * crop_size[1]:
            out.append("문제 대부분이 그림으로 들어감")
    if not any((k == "text" and str(v).strip()) or k in ("math", "image") for k, v in segs):
        out.append("인식된 내용 없음")
    from latex2hwp import latex_to_hwp
    for k, v in segs:
        if k != "math":
            continue
        if HANGUL.search(v):
            out.append("수식 속에 한글")
        if not _balanced(v):
            out.append("수식 괄호 짝이 안 맞음")
        try:
            latex_to_hwp(v)
        except Exception:  # noqa: BLE001
            out.append("한글 수식으로 못 바꾼 수식")
    text = "".join(v for k, v in segs if k == "text")
    marks = [c for c in text if c in CIRC]
    if marks and marks != list(CIRC[:len(marks)]):
        out.append("선지 번호 차례가 이상함")
    if any(k == "text" and v.startswith("[") and "인식 실패" in v for k, v in segs):
        out.append("인식 실패")
    return list(dict.fromkeys(out))


# ---------------------------------------------------------------- 저장·불러오기
def _paras_to_json(paras, k, figdir):
    if paras is None:
        return None
    out = []
    for i, para in enumerate(paras):
        row = []
        for j, (kind, v) in enumerate(para):
            if kind == "image":
                name = f"{k:03d}_{i}_{j}.png"
                v.img.save(os.path.join(figdir, name))
                row.append([kind, {"png": "figs/" + name, "kind": v.kind, "scale": v.scale, "em": v.em}])
            else:
                row.append([kind, v])
        out.append(row)
    return out


def _paras_from_json(data, wdir):
    if data is None:
        return None
    from passage import Figure
    out = []
    for para in data:
        row = []
        for kind, v in para:
            if kind == "image":
                with Image.open(os.path.join(wdir, v["png"])) as im:
                    f = Figure(im.convert("RGB"), v.get("kind", "image"), v.get("scale", 1.0))
                f.em = v.get("em")
                row.append((kind, f))
            else:
                row.append((kind, v))
        out.append(row)
    return out


def _plain(o):
    """numpy 숫자 등 → 파이썬 숫자"""
    if hasattr(o, "item"):
        return o.item()
    if hasattr(o, "__float__"):
        return float(o)
    raise TypeError(type(o).__name__)


def save(work: Work, crops=None):
    """work.json + 문제 그림(crops/) + 그림(figs/). crops: {문제 번호(k): 문제 그림} (처음 저장할 때)"""
    os.makedirs(os.path.join(work.dir, "figs"), exist_ok=True)
    os.makedirs(os.path.join(work.dir, "crops"), exist_ok=True)
    for k, im in (crops or {}).items():
        im.save(os.path.join(work.dir, "crops", f"{k:03d}.png"))
    figdir = os.path.join(work.dir, "figs")
    data = {
        "version": VERSION, "pdf": os.path.abspath(work.pdf), "out": os.path.abspath(work.out), "dpi": work.dpi,
        "figures": work.figures, "letters": list(work.letters) if work.letters else None,
        "page_info": [{k: (list(v) if isinstance(v, tuple) else v) for k, v in info.items()} for info in work.page_info],
        "probs": [asdict(p) for p in work.probs], "pinfo": work.pinfo,
        "results": [_paras_to_json(r, k, figdir) for k, r in enumerate(work.results)],
        "ems": work.ems, "flags": work.flags, "edited": work.edited,
        "regions": work.regions, "user_regions": work.user_regions,
    }
    tmp = os.path.join(work.dir, "work.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, default=_plain)
    os.replace(tmp, os.path.join(work.dir, "work.json"))


def load(wdir: str) -> Work:
    if os.path.isfile(wdir):  # work.json 을 골랐을 때
        wdir = os.path.dirname(wdir)
    with open(os.path.join(wdir, "work.json"), encoding="utf-8") as f:
        d = json.load(f)
    probs = []
    for p in d["probs"]:
        blocks = [L.Block(b["box"], b.get("text", "")) for b in p.pop("blocks")]
        probs.append(L.Problem(blocks=blocks, **p))
    page_info = []
    for info in d["page_info"]:
        info["cols"] = [tuple(c) for c in info["cols"]]
        info["size"] = tuple(info["size"])
        page_info.append(info)
    n = len(probs)
    return Work(dir=wdir, pdf=d["pdf"], out=d["out"], dpi=d["dpi"], figures=d.get("figures", True),
                letters=tuple(d["letters"]) if d.get("letters") else None, page_info=page_info, probs=probs,
                pinfo=d["pinfo"], results=[_paras_from_json(r, wdir) for r in d["results"]], ems=d.get("ems", []),
                flags=d.get("flags") or [[] for _ in range(n)], edited=d.get("edited") or [False] * n,
                regions=d.get("regions") or [[] for _ in range(n)],
                user_regions=d.get("user_regions") or [[] for _ in range(n)])


def crop_path(work: Work, k: int) -> str:
    return os.path.join(work.dir, "crops", f"{k:03d}.png")


# ---------------------------------------------------------------- 다시 읽기
def page_image(work: Work, page: int, scale: float = 1.0) -> Image.Image:
    doc = L.open_pdf(work.pdf)
    try:
        return L.render(doc, page, round(work.dpi * scale))
    finally:
        try:
            doc.close()
        except Exception:  # noqa: BLE001
            pass


def reread(work: Work, k: int, reader, box=None, scale: float = 1.0, regions=None):
    """문제 k 를 다시 읽음. box: 쪽 그림(변환 해상도 기준) 위 새 영역 [x0, y0, x1, y1] (없으면 원래 자리).
    scale: 해상도 배율 (2 = 두 배로 그려서 읽기). regions: 사용자가 정한 영역 (문제 그림 픽셀, box 없을 때만).
    → (문단들, 의심 이유, 문제 그림, 이번에 나눈 영역(문제 그림 픽셀, 배율 1 기준))"""
    p = work.probs[k]
    info = work.page_info[work.pinfo[k]]
    img = page_image(work, p.page, scale)

    def sc(b):
        return [int(round(v * scale)) for v in b]

    if box is not None:
        x0, y0, x1, y1 = box
        blocks = [L.Block(sc([min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]))]
        nb = p.num_box if (p.num_box and _overlap(p.num_box, box)) else None
    else:
        blocks = [L.Block(sc(b.box), b.text) for b in p.blocks]
        nb = p.num_box
    q = L.Problem(p.num, p.page, p.col, blocks, num_box=sc(nb) if nb else None, kind=p.kind)
    pim = L.problem_image(img, q, info["lh"] * scale)
    kw = {}
    if regions and box is None:
        kw["regions"] = [{"box": [v * scale for v in r["box"]], "kind": r["kind"]} for r in regions]
    paras = reader(pim, figures=work.figures, letters=work.letters, **kw)
    notes = list(getattr(reader, "notes", []))
    regs = [{"box": [v / scale for v in r["box"]], "kind": r["kind"]} for r in (getattr(reader, "last_regions", None) or [])]
    missing = 0
    if info.get("text"):
        try:
            doc = L.open_pdf(work.pdf)
            words = L.text_words(doc, p.page, work.dpi)
            missing = hangul_missing(words, [L.Block(b) for b in ([box] if box else [b.box for b in p.blocks])], paras)
        except Exception:  # noqa: BLE001
            pass
    return paras, problem_flags(paras, notes, pim.size, missing), pim, regs


def _overlap(a, b):
    """번호 자리 a 가 새 영역 b 와 겹치면 (번호를 지우고 인식)"""
    return a[0] < max(b[0], b[2]) and min(b[0], b[2]) < a[2] and a[1] < max(b[1], b[3]) and min(b[1], b[3]) < a[3]


def replace(work: Work, k: int, paras, flags, regions=None, user_regions=None):
    work.results[k] = paras
    work.flags[k] = flags
    work.edited[k] = True
    if regions is not None:
        work.regions[k] = regions
    if user_regions is not None:
        work.user_regions[k] = user_regions
    save(work)


# ---------------------------------------------------------------- 한 문제를 한글로 (클립보드)
def problem_hwp(work: Work, k: int, paras=None, body_pt: float | None = None):
    """문제 k (또는 주어진 문단들)를 한글 붙여넣기용 문단으로: 번호 "N. " 포함, 선지는 한 줄씩"""
    from pdf_convert import _put_number, _segs_for_hwp
    p = work.probs[k]
    paras = work.results[k] if paras is None else paras
    if paras is None:
        return []
    body_pt = body_pt or 10.0
    hwp = [_segs_for_hwp(para, body_pt) for para in paras]
    if p.num is not None:
        hwp = _put_number(hwp, p.num, bool(p.num_box))
    return hwp


def preview_text(paras, num=None) -> str:
    """확인 창에 보여 줄 글: 수식은 [한글 수식 스크립트], 그림은 [그림]"""
    if paras is None:
        return "(안내 상자)"
    from latex2hwp import latex_to_hwp
    lines = []
    for i, para in enumerate(paras):
        out = []
        for k, v in para:
            if k == "text":
                out.append(v)
            elif k == "image":
                out.append("[그림]")
            else:
                try:
                    out.append("〔" + latex_to_hwp(v) + "〕")
                except Exception:  # noqa: BLE001
                    out.append("〔LaTeX: " + v + "〕")
        line = "".join(out)
        if i == 0 and num is not None:
            line = f"{num}. " + line
        lines.append(line)
    return "\n".join(lines)


def body_pt(work: Work) -> float:
    """본문 글자 크기 (pdf_convert.build 와 같은 계산)"""
    import statistics
    em_px = statistics.median(work.ems) if work.ems else work.dpi * 10 / 72
    return min(14.0, max(8.0, round(em_px / work.dpi * 72 * 2) / 2))


def rebuild(work: Work, out_path: str | None = None):
    """작업 파일의 결과로 .hwpx 다시 저장 (인식은 다시 하지 않음)"""
    from pdf_convert import build
    return build(work.jobs(), work.results, work.page_info, work.ems, work.dpi, out_path or work.out)
