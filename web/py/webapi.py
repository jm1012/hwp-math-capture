"""웹 버전 진입점: py-worker.js 가 부른다. 인식·변환은 exe 와 같은 app 코드(pdf_convert, pdf_work)를 그대로 쓴다.

파일은 모두 브라우저 메모리 속 가상 폴더(/work)에만 있고 밖으로 나가지 않는다.
"""
from __future__ import annotations

import base64
import io
import json
import os
import shutil
import sys
import time

APP = os.path.dirname(os.path.abspath(__file__))
WORK = "/work"
_rec = None
_work = None          # 지금 문제 확인 중인 pdf_work.Work
_cand = {}            # 문제 번호 → 다시 읽은 후보 (문단들, 의심 이유, 문제 그림, 영역, 사용자 영역)
_works = {}           # 작업(PDF) 번호 → Work. PDF 마다 /work/<번호>/ 폴더


def _png(im) -> str:
    b = io.BytesIO()
    im.save(b, "PNG")
    return base64.b64encode(b.getvalue()).decode()


def setup(placeholders: list[str]) -> dict:
    """모델 자리(빈 파일)를 만들고 인식기를 불러온다. placeholders: model 폴더 기준 onnx 이름들"""
    global _rec
    import onnxruntime
    mdir = os.path.join(APP, "model")
    onnxruntime.MODEL_ROOT = mdir
    for rel in placeholders:
        p = os.path.join(mdir, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if not os.path.exists(p):
            open(p, "wb").close()
    t0 = time.time()
    _patch_mfr(mdir)
    from recognizer import Recognizer
    r = Recognizer()
    r._load()
    if r.error:
        raise r.error
    _rec = r
    return {"seconds": round(time.time() - t0, 1), "figures": r.passage.figures is not None}


def _patch_mfr(mdir):
    """수식 인식 디코더의 첫 계산(인코더 출력 → cross-attention K/V, 큰 행렬 곱 12개)을 ORT 로.
    브라우저 numpy 에는 빠른 행렬 곱(BLAS)이 없어 문제 하나에 몇 초씩 걸림. 계산식은 mfr.KVDecoder.start 와 같음."""
    import numpy as np
    import onnxruntime
    import mfr
    path = os.path.join(mdir, "mfr", "cross_kv.onnx")
    if not os.path.isfile(path):
        return
    sess = onnxruntime.InferenceSession(path)

    def start(self, enc):
        y = sess.run(None, {"enc": np.ascontiguousarray(enc, dtype=np.float32)})[0]
        B, T = y.shape[:2]
        y = y.reshape(B, T, self.LAYERS, 2, self.D)
        st = {"t": 0, "ck": [], "cv": [], "sk": [None] * self.LAYERS, "sv": [None] * self.LAYERS}
        for i in range(self.LAYERS):
            st["ck"].append(self._heads(np.ascontiguousarray(y[:, :, i, 0])))
            st["cv"].append(self._heads(np.ascontiguousarray(y[:, :, i, 1])))
        return st

    mfr.KVDecoder.start = start


class _Cancel:
    def is_set(self):
        from js import cancelFlag  # py-worker.js
        return bool(cancelFlag())


def convert(job: int, pdf_path: str, out_name: str, opts_json: str, progress) -> str:
    """PDF → .hwpx. progress(완료, 전체, 글). 결과: 보고서 JSON (hwpx 는 out 경로에 저장)"""
    global _work, _cand
    from pdf_convert import convert as conv
    opts = json.loads(opts_json or "{}")
    jdir = os.path.join(WORK, str(job))
    if os.path.isdir(jdir):
        shutil.rmtree(jdir)
    os.makedirs(jdir)
    out = os.path.join(jdir, out_name)
    wdir = os.path.join(jdir, "작업")
    letters = (bool(opts.get("letters_bold", True)), bool(opts.get("letters_italic", False))) \
        if opts.get("letters_unify", True) else None
    rep = conv(pdf_path, out, _rec.passage, pages=opts.get("pages") or None, dpi=int(opts.get("dpi", 150)),
               figures=bool(opts.get("figures", True)), letters=letters, work_dir=wdir,
               progress=lambda d, t, m: progress(d, t, m), cancel=_Cancel())
    import pdf_work as W
    w = W.load(wdir)
    w.pdf, w.out = pdf_path, out
    _works[job] = w
    return json.dumps({"text": rep.text(), "out": out, "pages": rep.pages, "problems": rep.problems,
                       "seconds": rep.seconds, "counts": rep.counts, "flagged": len(rep.flagged)}, ensure_ascii=False)


def use_job(job: int):
    """문제 확인할 PDF 고르기"""
    global _work, _cand
    _work = _works[job]
    _cand = {}


def zip_outs(files_json: str) -> str:
    """[{job, name}] → 한 zip 파일 (경로를 돌려줌)"""
    import zipfile
    files = json.loads(files_json)
    path = os.path.join(WORK, "all.zip")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:
        for f in files:
            z.write(_works[f["job"]].out, f["name"])
    return path


def read_file(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


# ---------------------------------------------------------------- 문제 확인
def problems() -> str:
    """문제 목록: [{k, label, flags, edited, kind}]"""
    w = _work
    return json.dumps([{"k": k, "label": w.label(k), "flags": w.flags[k], "edited": bool(w.edited[k]),
                        "kind": w.probs[k].kind} for k in range(len(w.probs))], ensure_ascii=False)


def _view(paras, num):
    """확인 창에 보일 결과: 문단마다 [["text", 글], ["math", LaTeX, 한글 수식], ["image", png]]"""
    from latex2hwp import latex_to_hwp
    if paras is None:
        return None
    out = []
    for i, para in enumerate(paras):
        row = []
        if i == 0 and num is not None:
            row.append(["text", f"{num}. "])
        for k, v in para:
            if k == "text":
                row.append(["text", v])
            elif k == "image":
                row.append(["image", _png(v.img)])
            else:
                try:
                    h = latex_to_hwp(v)
                except Exception:  # noqa: BLE001
                    h = None
                row.append(["math", v, h])
        out.append(row)
    return out


def problem(k: int) -> str:
    import pdf_work as W
    from PIL import Image
    w = _work
    p = w.probs[k]
    try:
        with Image.open(W.crop_path(w, k)) as im:
            crop = _png(im.convert("RGB"))
    except OSError:  # 안내 상자는 인식하지 않아 문제 그림을 저장하지 않음 → 쪽 그림에서 잘라 보여 줌
        try:
            crop = _png(W.page_image(w, p.page).crop(tuple(round(v) for v in p.box)))
        except Exception:  # noqa: BLE001
            crop = None
    result = _view(w.results[k], p.num)
    if result is None and p.kind == "notice":
        from pdf_convert import notice_paragraphs
        try:
            result = [[["text", t]] for t in notice_paragraphs(p.blocks[0].text)]
        except Exception:  # noqa: BLE001
            result = None
    return json.dumps({"k": k, "label": w.label(k), "num": p.num, "kind": p.kind, "flags": w.flags[k],
                       "crop": crop, "result": result,
                       "regions": w.regions[k] if k < len(w.regions) else [],
                       "user_regions": w.user_regions[k] if k < len(w.user_regions) else [],
                       "page": p.page, "box": p.box}, ensure_ascii=False)


def page_image(page: int) -> str:
    """문제 영역 다시 잡기용 쪽 그림 (변환 해상도)"""
    import pdf_work as W
    return _png(W.page_image(_work, page))


def reread(k: int, opts_json: str) -> str:
    """opts: {scale, box, regions}. 후보로 두고 보여 줌 (accept 해야 바뀜)"""
    import pdf_work as W
    from PIL import Image
    o = json.loads(opts_json or "{}")
    scale, box, regions = float(o.get("scale", 1.0)), o.get("box"), o.get("regions")
    paras, fl, pim, regs = W.reread(_work, k, _rec.passage, box=box, scale=scale, regions=regions)
    if scale != 1:
        pim = pim.resize((round(pim.width / scale), round(pim.height / scale)), Image.LANCZOS)
    ureg = regions if regions is not None else ([] if box is not None else None)
    _cand[k] = (paras, fl, pim, regs, ureg)
    return json.dumps({"k": k, "flags": fl, "result": _view(paras, _work.probs[k].num), "crop": _png(pim)},
                      ensure_ascii=False)


def accept(k: int) -> str:
    import pdf_work as W
    paras, fl, pim, regs, ureg = _cand.pop(k)
    W.replace(_work, k, paras, fl, regions=regs, user_regions=ureg)
    pim.save(W.crop_path(_work, k))
    return problem(k)


def drop(k: int):
    _cand.pop(k, None)


def rebuild() -> str:
    """바꾼 결과로 .hwpx 다시 만들기 (인식은 다시 하지 않음)"""
    import pdf_work as W
    counts = W.rebuild(_work)
    return json.dumps({"out": _work.out, "counts": counts}, ensure_ascii=False)


# ---------------------------------------------------------------- 시험용 (184장 회귀)
def read_image(png_path: str) -> str:
    """문제 그림 한 장 → 문단들 (exe 의 지문 캡처와 같은 경로: Recognizer.read_passage)"""
    from PIL import Image
    from latex2hwp import latex_to_hwp
    from passage import to_markdown
    t0 = time.time()
    with Image.open(png_path) as im:
        paras = _rec.read_passage(im.convert("RGB"))

    def hw(v):
        try:
            return latex_to_hwp(v)
        except Exception as e:  # noqa: BLE001
            return f"[변환 실패 {e}]"
    hwp = [[(k, v if k == "text" else ("[img]" if k == "image" else hw(v))) for k, v in p] for p in paras]
    return json.dumps({"hwp": hwp, "md": to_markdown(paras), "sec": round(time.time() - t0, 2)},
                      ensure_ascii=False, default=lambda o: "[img]")


if APP not in sys.path:
    sys.path.insert(0, APP)
