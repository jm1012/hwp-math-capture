"""PDF 파일 하나 → 한글 문서(.hwpx). 원본처럼 2단, 문제마다 글자·수식·그림.

흐름: 쪽 그림 만들기 → (있으면) PDF 글자 정보 → 단·문제 나누기(pdf_layout) → 문제마다 지문 인식(passage)
      → 한글 수식 스크립트로 바꿈 → .hwpx 저장(hwpx_writer)

명령줄: python pdf_convert.py 입력.pdf [출력.hwpx] [--pages 1-20] [--dpi 150]
"""
from __future__ import annotations

import re
import statistics
import time
from dataclasses import dataclass, field

import pdf_layout as L

ANSWER_PAGE = re.compile(r"정\s*답")


@dataclass
class Report:
    pages: int = 0
    done_pages: list = field(default_factory=list)
    skipped: list = field(default_factory=list)      # (쪽 번호, 이유)
    problems: list = field(default_factory=list)     # 찾은 문제 번호 (순서대로)
    warnings: list = field(default_factory=list)
    seconds: float = 0.0
    counts: dict = field(default_factory=dict)
    flagged: list = field(default_factory=list)     # (쪽, 번호, 의심 이유) — 문제 확인 창에서 볼 것
    work_dir: str | None = None

    def text(self) -> str:
        nums = ", ".join(str(n) for n in self.problems)
        out = [f"쪽 {len(self.done_pages)}/{self.pages} 변환, 문제 {len(self.problems)}개 ({nums}), {self.seconds:.0f}초"]
        if self.counts:
            out.append(f"문단 {self.counts.get('paragraphs', 0)}개, 수식 {self.counts.get('equations', 0)}개, "
                       f"그림 {self.counts.get('pictures', 0)}개")
        # 같은 이유로 이어진 쪽은 묶어서 ("21~40쪽 건너뜀: 짝수형 …")
        runs = []
        for p, why in self.skipped:
            if runs and runs[-1][2] == why and runs[-1][1] == p - 1:
                runs[-1][1] = p
            else:
                runs.append([p, p, why])
        out += [f"{a}쪽 건너뜀: {why}" if a == b else f"{a}~{b}쪽 건너뜀: {why}" for a, b, why in runs]
        out += self.warnings
        if self.flagged:
            out.append(f"확인해 볼 문제 {len(self.flagged)}개 ([문제 확인] 에서 볼 수 있음)")
        return "\n".join(out)


class Cancelled(Exception):
    pass


def parse_pages(spec: str | None, n: int) -> list[int]:
    """'1-20,25' → 0부터 쪽 번호 목록. 비어 있으면 전부"""
    if not spec or not spec.strip():
        return list(range(n))
    out = []
    for part in spec.replace(" ", "").split(","):
        if not part:
            continue
        a, _, b = part.partition("-")
        a = int(a) if a else 1
        b = int(b) if b else (n if _ else a)
        out += [i - 1 for i in range(a, b + 1) if 1 <= i <= n]
    return sorted(set(out))


def _segs_for_hwp(para, body_pt):
    from hwp_clipboard import figure_for_hwp
    from latex2hwp import latex_to_hwp
    out = []
    for k, v in para:
        if k == "text":
            out.append(("text", v))
        elif k == "image":
            out.append(("pic", figure_for_hwp(v, body_pt)))
        else:
            try:
                out.append(("eq", latex_to_hwp(v)))
            except Exception:  # noqa: BLE001
                out.append(("eq", v))
    return out


CIRC = "①②③④⑤⑥⑦⑧⑨⑩"


def _is_choice_para(segs):
    if not segs or any(k not in ("text", "eq") for k, _ in segs) or segs[0][0] != "text":
        return False
    return segs[0][1].lstrip()[:1] in CIRC


def _split_choices(segs):
    """선지 문단(들)의 조각을 번호(①…)마다 나눔: [[("text", "① "), ("eq", …)], …]"""
    items = []
    for k, v in segs:
        if k == "text":
            for part in re.split(f"([{CIRC}])", v):
                if not part:
                    continue
                if part in CIRC:
                    items.append([("text", part + " ")])
                elif part.strip() and items:
                    items[-1].append(("text", part.strip()))
        elif items:
            items[-1].append((k, v))
    return items


def group_choices(hwp):
    """이어진 선지 문단(원본에서 한 줄이든 여러 줄이든)을 하나의 ("choices", 선지들) 로: 배치는 한글 파일 쓸 때 정함.
    번호가 ①부터 차례대로일 때만 (아니면 그대로 둠)"""
    out, i = [], 0
    while i < len(hwp):
        if not _is_choice_para(hwp[i]):
            out.append(hwp[i])
            i += 1
            continue
        j = i
        while j < len(hwp) and _is_choice_para(hwp[j]):
            j += 1
        items = _split_choices([s for para in hwp[i:j] for s in para])
        marks = [it[0][1][0] for it in items]
        if len(items) >= 2 and marks == list(CIRC[:len(items)]) and all(len(it) > 1 for it in items):
            out.append([("choices", items)])
        else:
            out += hwp[i:j]
        i = j
    return out


def notice_paragraphs(text):
    """안내 상자의 줄들 → 문단들: ○·◦ 로 시작하는 줄에서 새 문단, 아니면 앞 줄에 이어 붙임"""
    out = []
    for ln in text.splitlines():
        ln = ln.strip()
        if re.match(r"^[ㅇ◦°•](?=\S)|^[ㅇoO0◦°•]\s", ln):  # 동그라미 글머리 (OCR 은 ㅇ, o, 0 로 읽음)
            ln = "○ " + ln[1:].lstrip()
        if not ln:
            continue
        if out and not ln.startswith("○"):
            out[-1] += " " + ln
        else:
            out.append(ln)
    return out


_LEAD_NUM = re.compile(r"^\s*\d{1,2}\s*[.,]\s*")


def _put_number(hwp, num, erased):
    """문제 첫 문단 앞에 번호 "N. " 를 글자로. 번호를 못 지운 경우 인식된 번호(글자/수식)는 뺌"""
    if not hwp:
        return [[("text", f"{num}. ")]]
    first = list(hwp[0])
    if not erased:
        while first and first[0][0] == "eq" and re.fullmatch(r"[\s{}]*(?:bold|rm|it)?[\s{}]*\d{1,2}[\s{}.,]*", first[0][1]):
            first.pop(0)
            if first and first[0][0] == "text":
                first[0] = ("text", first[0][1].lstrip(" .,"))
        if first and first[0][0] == "text":
            first[0] = ("text", _LEAD_NUM.sub("", first[0][1], count=1))
    if first and first[0][0] == "text":
        first[0] = ("text", f"{num}. " + first[0][1].lstrip())
    else:
        first.insert(0, ("text", f"{num}. "))
    return [first] + hwp[1:]


def convert(pdf_path: str, out_path: str, reader, *, pages: str | None = None, dpi: int = 150,
            figures: bool = True, letters=None, progress=None, cancel=None, log=None, debug_dir=None, work_dir=None) -> Report:
    """reader: passage.PassageReader (또는 같은 꼴로 부를 수 있는 것, rec_image 필요).
    progress(완료 수, 전체 수, 글) 로 진행 상황을 알림. cancel: threading.Event (set 되면 멈춤, 지금까지 결과는 저장 안 함)"""
    from hwpx_writer import write_hwpx

    t0 = time.time()
    doc = L.open_pdf(pdf_path)
    idx = parse_pages(pages, len(doc))
    rep = Report(pages=len(idx))
    say = progress or (lambda *a: None)

    # 1) 쪽마다 단·문제 나누기
    page_info, jobs = [], []   # jobs: (쪽 번호, Problem, 쪽 그림)
    page_words = {}
    seen_problem = False
    odd_even = None
    for n, i in enumerate(idx):
        if cancel is not None and cancel.is_set():
            raise Cancelled
        say(n, len(idx) * 4, f"{i + 1}쪽 나누는 중")
        words = L.text_words(doc, i, dpi)
        alltext = " ".join(w["val"] for w in words)
        if len(ANSWER_PAGE.findall(alltext)) >= 5:
            rep.skipped.append((i + 1, "정답 쪽"))
            continue
        # 수능 PDF 뒤쪽의 짝수형: 홀수형 쪽이 먼저 나왔으면 건너뜀
        head = " ".join(w["val"] for w in words[:40])
        kind = "홀수형" if "홀수형" in head else "짝수형" if "짝수형" in head else None
        if kind:
            if odd_even is None:
                odd_even = kind
            elif kind != odd_even:
                rep.skipped.append((i + 1, f"{kind} (앞의 {odd_even}과 같은 문제)"))
                continue
        if not L.has_text_layer(words):
            words = []
        img = L.render(doc, i, dpi)
        probs, info = L.split_page(img, words, i, dpi, rec=reader.rec_image)
        if not any(p.num is not None for p in probs) and not seen_problem:
            rep.skipped.append((i + 1, "문제 번호 없음 (표지·안내)"))
            continue
        if not probs:
            rep.skipped.append((i + 1, "빈 쪽"))
            continue
        seen_problem = seen_problem or any(p.num is not None for p in probs)
        info.update(page=i, size=img.size, text=bool(words))
        page_words[i] = words
        page_info.append(info)
        rep.done_pages.append(i + 1)
        for p in probs:
            jobs.append((p, img, info))
            if p.num is not None:
                rep.problems.append(p.num)
    if not jobs:
        raise RuntimeError("PDF에서 문제를 찾지 못했습니다.")

    # 2) 문제마다 인식
    results = []
    ems = []
    flags, crops, regions = [], {}, []
    from pdf_work import hangul_missing, problem_flags
    total = len(jobs)
    base = len(idx)
    for k, (p, img, info) in enumerate(jobs):
        if cancel is not None and cancel.is_set():
            raise Cancelled
        if p.kind == "notice":
            results.append(None)
            flags.append([])
            regions.append([])
            continue
        label = f"{p.page + 1}쪽 " + (f"{p.num}번" if p.num is not None else "(이어지는 내용)")
        say(base + 3 * base * k // total, base * 4, f"{label} 인식 중")
        pim = L.problem_image(img, p, info["lh"])
        try:
            paras = reader(pim, figures=figures, letters=letters)
        except Exception as e:  # noqa: BLE001  한 문제가 실패해도 나머지는 계속
            rep.warnings.append(f"{label} 인식 실패: {e}")
            paras = [[("text", f"[{label} 인식 실패]")]]
        if getattr(reader, "last_em", None):
            ems.append(reader.last_em)
        results.append(paras)
        regions.append(list(getattr(reader, "last_regions", []) or []))
        miss = hangul_missing(page_words.get(p.page) or [], p.blocks, paras)
        flags.append(problem_flags(paras, getattr(reader, "notes", []), pim.size, miss))
        if work_dir:
            crops[k] = pim
        if debug_dir:  # 문제 그림과 인식 결과(LaTeX)를 남김: 오류 원인 찾기용
            import json
            import os
            os.makedirs(debug_dir, exist_ok=True)
            tag = f"p{p.page + 1:02d}_c{p.col}_{p.num if p.num is not None else 'x'}_{k:03d}"
            pim.save(os.path.join(debug_dir, tag + ".png"))
            with open(os.path.join(debug_dir, tag + ".json"), "w", encoding="utf-8") as fp:
                json.dump(paras, fp, ensure_ascii=False, default=lambda o: "[img]")
        if log:
            log(f"{label}: 문단 {len(paras)}개")

    # 3) 작업 파일 (문제 확인 창에서 다시 읽기·다시 저장)
    if work_dir:
        from pdf_work import Work, save
        ids = {id(info): n for n, info in enumerate(page_info)}
        save(Work(dir=work_dir, pdf=pdf_path, out=out_path, dpi=dpi, figures=figures, letters=letters,
                  page_info=page_info, probs=[p for p, _, _ in jobs], pinfo=[ids[id(inf)] for _, _, inf in jobs],
                  results=results, ems=ems, flags=flags, edited=[False] * len(jobs), regions=regions), crops)
        rep.work_dir = work_dir
    rep.flagged = [(p.page + 1, p.num, f) for (p, _, _), f in zip(jobs, flags) if f]

    say(base * 4 - 1, base * 4, "한글 파일 저장 중")
    rep.counts = build([(p, inf) for p, _, inf in jobs], results, page_info, ems, dpi, out_path)
    # 빠진 번호 경고 (1, 2, 4 → 3번 없음). 선택과목처럼 번호가 다시 작아지는 곳은 새 묶음으로 봄
    nums = rep.problems
    for a, b in zip(nums, nums[1:]):
        if b > a + 1:
            rep.warnings.append(f"{a}번과 {b}번 사이 문제를 찾지 못함")
    rep.seconds = time.time() - t0
    say(base * 4, base * 4, "완료")
    return rep


def build(jobs, results, page_info, ems, dpi, out_path):
    """인식 결과 → .hwpx (다시 인식하지 않음). jobs: (문제, 쪽 정보) 목록. → 문단·수식·그림 개수"""
    from hwpx_writer import write_hwpx
    # 글자 크기·쪽 여백 (원본에서 잼)
    em_px = statistics.median(ems) if ems else dpi * 10 / 72
    body_pt = min(14.0, max(8.0, round(em_px / dpi * 72 * 2) / 2))
    px2pt = 72 / dpi
    W, H = page_info[0]["size"]
    lefts, rights, gaps = [], [], []
    for info in page_info:
        cs = info["cols"]
        pb = [p.box for p, inf in jobs if inf is info]
        if not pb:
            continue
        c0 = [b for p, inf in jobs if inf is info and p.col == 0 for b in [p.box]]
        c1 = [b for p, inf in jobs if inf is info and p.col == len(cs) - 1 and len(cs) > 1 for b in [p.box]]
        lefts.append(min(b[0] for b in pb))
        rights.append(max(b[2] for b in pb))
        if c0 and c1:
            gaps.append(min(b[0] for b in c1) - max(b[2] for b in c0))
    ncols = max(len(info["cols"]) for info in page_info)
    left = statistics.median(lefts) * px2pt if lefts else 42
    right = (W - statistics.median(rights)) * px2pt if rights else 42
    top = statistics.median(info["top"] for info in page_info) * px2pt
    bot = (H - statistics.median(info["bot"] for info in page_info)) * px2pt
    gap = statistics.median(gaps) * px2pt if gaps else 24
    left, right = max(14.0, left - 4), max(14.0, right - 4)
    top, bot = max(14.0, min(top, 0.25 * H * px2pt)), max(14.0, min(bot, 0.2 * H * px2pt))
    col_h = H * px2pt - top - bot

    # 문서 만들기: 원본 단이 바뀌면 단 나누기, 문제 사이 빈칸은 원본 간격만큼
    items = []
    prev_key, prev_bottom = None, None
    for (p, info), paras in zip(jobs, results):
        if p.kind == "notice":
            b = p.blocks[0].box
            items.append({"notice": True, "lines": notice_paragraphs(p.blocks[0].text),
                          "box_pt": (b[0] * px2pt, b[1] * px2pt, (b[2] - b[0]) * px2pt, (b[3] - b[1]) * px2pt)})
            continue
        key = (p.page, p.col)
        box = p.box
        if key != prev_key:
            space = (box[1] - info["top"]) * px2pt
            col_break = prev_key is not None
        else:
            space = (box[1] - prev_bottom) * px2pt
            col_break = False
        space = max(0.0, min(0.6 * col_h, 0.9 * space))
        if col_break or prev_key is None or key != prev_key:
            space = min(space, 3 * body_pt)  # 단 첫 문제: 위 안내 상자(5지선다형 등)를 뺀 자리만큼 비우지 않음
        hwp = [_segs_for_hwp(para, body_pt) for para in paras]
        if p.num is not None:
            hwp = _put_number(hwp, p.num, bool(p.num_box))
        hwp = group_choices(hwp)
        prev_item = next((x for x in reversed(items) if not x.get("notice")), None)
        if p.num is None and prev_item is not None and not col_break:
            prev_item["paras"] += hwp
        else:
            items.append({"paras": hwp, "col_break": col_break, "space_pt": space if space > body_pt else 0})
        prev_key, prev_bottom = key, box[3]

    return write_hwpx(out_path, items, page_w_pt=W * px2pt, page_h_pt=H * px2pt,
                            margins_pt=(left, right, top, bot), cols=ncols, col_gap_pt=gap, body_pt=body_pt)


def default_reader():
    """명령줄용: 앱과 같은 인식기"""
    from recognizer import Recognizer
    r = Recognizer()
    r._load()
    if r.error:
        raise r.error
    return r.passage


if __name__ == "__main__":
    import argparse
    import os

    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--pages", default="")
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--debug", default="", help="문제 그림·인식 결과를 남길 폴더")
    ap.add_argument("--no-work", action="store_true", help="작업 폴더(<이름>_작업)를 만들지 않음")
    a = ap.parse_args()
    out = a.out or os.path.splitext(a.pdf)[0] + ".hwpx"
    rd = default_reader()
    rep = convert(a.pdf, out, rd, pages=a.pages, dpi=a.dpi, letters=(True, False), debug_dir=a.debug or None,
                  work_dir=None if a.no_work else os.path.splitext(out)[0] + "_작업",
                  progress=lambda d, t, m: print(f"[{d}/{t}] {m}", flush=True))
    print(rep.text())
    print("저장:", out)
