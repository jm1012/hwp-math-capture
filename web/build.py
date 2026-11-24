"""웹 버전 빌드: web/dist 에 정적 사이트를 만든다 (GitHub Pages 에 그대로 올림).

    python web/build.py [--models 모델폴더] [--out web/dist]

- 브라우저 파이썬(Pyodide), onnxruntime-web, PDFium(wasm) 을 npm·jsDelivr 에서 받아 vendor/ 에 넣는다 (해시 확인).
- app/*.py (인식·변환 코드, exe 와 같은 코드) + web/py (브라우저용 대체 모듈) → py/app.zip
- --models: models.py prepare 로 만든 파생 파일(encoder_int8.onnx, decoder_kv.npz, rec_korean_dict.txt)과
  tokenizer.json 을 models/ 에 넣는다. 나머지 큰 모델은 브라우저가 Hugging Face 에서 직접 받는다.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
APP = os.path.join(ROOT, "app")
CACHE = os.path.join(WEB, ".cache")

PYODIDE = "314.0.7"
NPM = {"pyodide": PYODIDE, "onnxruntime-web": "1.31.1", "@embedpdf/pdfium": "2.15.1", "coi-serviceworker": "0.1.7", "katex": "0.19.1"}
# Pyodide 에 들어 있는 패키지 (jsDelivr 의 Pyodide 배포본에서 받음, 의존 패키지도 같이)
PYODIDE_PKGS = ["numpy", "opencv-python", "pillow", "lxml", "shapely", "pyclipper", "pyyaml", "requests", "tqdm", "six"]
# PyPI 의 순수 파이썬 패키지
PYPI = ["rapidocr==3.10.0", "omegaconf==2.4.0", "colorlog==6.12.0", "python-hwpx==7.0.1"]
# app 모듈 중 브라우저에 넣지 않는 것 (창·단축키·빌드·시험)
APP_EXCLUDE = {"app", "hotkey", "overlay", "dropfiles", "pdf_dialog", "review_dialog", "build_exe", "check_deps",
               "paste_test", "smoke_test"}
# 원문자 견본용 글꼴 (NanumGothic, OFL): koreanize-matplotlib 휠 속 파일에서 필요한 글자만 남김
FONT_WHEEL = "koreanize-matplotlib==0.1.1"
# 파생 모델 (models.py prepare) — 나머지는 config.json 의 Hugging Face 주소에서 받음
LOCAL_MODELS = ["mfr/encoder_int8.onnx", "mfr/decoder_kv.npz", "mfr/tokenizer.json", "ocr/rec_korean_dict.txt"]


def fetch(url: str) -> bytes:
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest())
    if os.path.isfile(path):
        with open(path, "rb") as f:
            return f.read()
    print("받는 중:", url, flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "hwp-math-capture-web-build"})
    with urllib.request.urlopen(req) as r:
        data = r.read()
    with open(path + ".part", "wb") as f:
        f.write(data)
    os.replace(path + ".part", path)
    return data


def npm_package(name: str, ver: str) -> tarfile.TarFile:
    meta = json.loads(fetch(f"https://registry.npmjs.org/{name}/{ver}"))
    data = fetch(meta["dist"]["tarball"])
    algo, want = meta["dist"]["integrity"].split("-", 1)
    got = base64.b64encode(hashlib.new(algo, data).digest()).decode()
    if got != want:
        raise SystemExit(f"{name}@{ver}: 해시가 다름")
    return tarfile.open(fileobj=io.BytesIO(data))


def extract(tf: tarfile.TarFile, names: list[str], dst: str):
    os.makedirs(dst, exist_ok=True)
    for n in names:
        m = tf.getmember("package/" + n)
        with tf.extractfile(m) as src, open(os.path.join(dst, os.path.basename(n)), "wb") as out:
            shutil.copyfileobj(src, out)


def build_vendor(out: str):
    v = os.path.join(out, "vendor")
    # Pyodide 본체 + 패키지
    tf = npm_package("pyodide", PYODIDE)
    core = ["pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"]
    extract(tf, core, os.path.join(v, "pyodide"))
    lock = json.loads(open(os.path.join(v, "pyodide", "pyodide-lock.json"), "rb").read())
    pk = lock["packages"]
    need, todo = set(), list(PYODIDE_PKGS)
    while todo:
        n = todo.pop()
        if n in need:
            continue
        need.add(n)
        todo += pk[n]["depends"]
    for n in sorted(need):
        info = pk[n]
        data = fetch(f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE}/full/{info['file_name']}")
        if hashlib.sha256(data).hexdigest() != info["sha256"]:
            raise SystemExit(f"{n}: 해시가 다름")
        with open(os.path.join(v, "pyodide", info["file_name"]), "wb") as f:
            f.write(data)
    # onnxruntime-web (WebGPU + WASM)
    tf = npm_package("onnxruntime-web", NPM["onnxruntime-web"])
    extract(tf, ["dist/ort.webgpu.min.mjs", "dist/ort-wasm-simd-threaded.jsep.mjs", "dist/ort-wasm-simd-threaded.jsep.wasm",
                 "dist/ort-wasm-simd-threaded.asyncify.mjs", "dist/ort-wasm-simd-threaded.asyncify.wasm",
                 "dist/ort-wasm-simd-threaded.mjs", "dist/ort-wasm-simd-threaded.wasm"], os.path.join(v, "ort"))
    # PDFium (wasm): exe 의 pypdfium2 와 같은 엔진
    tf = npm_package("@embedpdf/pdfium", NPM["@embedpdf/pdfium"])
    extract(tf, ["dist/index.browser.js", "dist/pdfium.wasm", "LICENSE", "LICENSE.pdfium"], os.path.join(v, "pdfium"))
    # GitHub Pages 는 헤더를 못 바꾸므로 서비스 워커로 cross-origin isolation (SharedArrayBuffer 용)
    tf = npm_package("coi-serviceworker", NPM["coi-serviceworker"])
    extract(tf, ["coi-serviceworker.min.js"], out)
    extract(tf, ["LICENSE"], os.path.join(v, "coi"))
    # KaTeX: 문제 확인 창에서 인식된 수식을 보기 좋게 그림
    tf = npm_package("katex", NPM["katex"])
    extract(tf, ["dist/katex.min.js", "dist/katex.min.css", "LICENSE"], os.path.join(v, "katex"))
    fonts = [m.name[len("package/"):] for m in tf.getmembers() if m.name.startswith("package/dist/fonts/")
             and m.name.endswith(".woff2")]
    extract(tf, fonts, os.path.join(v, "katex", "fonts"))


def build_wheels(out: str):
    d = os.path.join(out, "wheels")
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(CACHE, "pypi")
    os.makedirs(tmp, exist_ok=True)
    subprocess.check_call([sys.executable, "-m", "pip", "download", "-q", "--no-deps", "--only-binary=:all:",
                           "--python-version", "3.14", "--platform", "any", "-d", tmp] + PYPI)
    names = []
    for spec in PYPI:
        pkg, ver = spec.split("==")
        stem = pkg.replace("-", "_").lower() + "-" + ver + "-"
        f = next(x for x in os.listdir(tmp) if x.lower().startswith(stem) and x.endswith(".whl"))
        _copy_wheel(os.path.join(tmp, f), os.path.join(d, f))
        names.append(f)
    return names


def _copy_wheel(src: str, dst: str):
    """휠 복사. rapidocr 휠 속 기본 모델(30MB, 쓰지 않음: 한국어 모델은 따로 받음)은 뺀다"""
    with zipfile.ZipFile(src) as zi, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zo:
        for it in zi.infolist():
            if it.filename.endswith(".onnx"):
                continue
            data = zi.read(it)
            if it.filename.endswith(".dist-info/RECORD"):
                data = b"".join(ln for ln in data.splitlines(True) if b".onnx," not in ln)
            zo.writestr(it, data)


def build_font(out: str):
    from fontTools import subset
    tmp = os.path.join(CACHE, "font")
    os.makedirs(tmp, exist_ok=True)
    subprocess.check_call([sys.executable, "-m", "pip", "download", "-q", "--no-deps", "-d", tmp, FONT_WHEEL])
    whl = next(os.path.join(tmp, x) for x in os.listdir(tmp) if x.endswith(".whl"))
    with zipfile.ZipFile(whl) as z:
        data = z.read("koreanize_matplotlib/fonts/NanumGothic.ttf")
    sys.path.insert(0, APP)
    import marks
    chars = set(marks.CIRCLED + marks.DIGITS + list(getattr(marks, "JAMO", "")))
    opt = subset.Options()
    opt.notdef_outline = True
    opt.hinting = True
    font = subset.load_font(io.BytesIO(data), opt)
    sub = subset.Subsetter(opt)
    sub.populate(unicodes=[ord(c) for c in chars])
    sub.subset(font)
    os.makedirs(os.path.join(out, "fonts"), exist_ok=True)
    subset.save_font(font, os.path.join(out, "fonts", "NanumGothic.ttf"), opt)


def build_py(out: str):
    os.makedirs(os.path.join(out, "py"), exist_ok=True)
    with zipfile.ZipFile(os.path.join(out, "py", "app.zip"), "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(os.listdir(APP)):
            m = f[:-3]
            if f.endswith(".py") and m not in APP_EXCLUDE and not m.startswith("test_"):
                z.write(os.path.join(APP, f), f)
        for f in os.listdir(os.path.join(APP, "spacing_data")):
            z.write(os.path.join(APP, "spacing_data", f), "spacing_data/" + f)
        pyd = os.path.join(WEB, "py")
        for base, _, files in os.walk(pyd):
            for f in files:
                if f.endswith(".py"):
                    p = os.path.join(base, f)
                    z.write(p, os.path.relpath(p, pyd))


def build_models(out: str, mdir: str):
    for rel in LOCAL_MODELS:
        dst = os.path.join(out, "models", *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy(os.path.join(mdir, *rel.split("/")), dst)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(WEB, "dist"))
    ap.add_argument("--models", default="", help="models.py prepare 를 마친 모델 폴더 (파생 파일을 사이트에 넣음)")
    a = ap.parse_args()
    out = a.out
    os.makedirs(out, exist_ok=True)
    build_vendor(out)
    wheels = build_wheels(out)
    build_font(out)
    build_py(out)
    if a.models:
        build_models(out, a.models)
    for f in os.listdir(os.path.join(WEB, "src")):
        shutil.copy(os.path.join(WEB, "src", f), os.path.join(out, f))
    sys.path.insert(0, APP)
    import models
    from pdf_convert import __doc__ as _  # noqa: F401  (app 코드가 import 되는지 확인)
    m = re.search(r'APP_VERSION", "([^"]+)"', open(os.path.join(APP, "build_exe.py"), encoding="utf-8").read())
    ver = m.group(1) if m else ""
    manifest = {
        "version": ver,
        "pyodide_packages": sorted(PYODIDE_PKGS),
        "wheels": wheels,
        "hf": {k: models.HF + "/" + v for k, v in models.FILES.items() if not k.endswith(".yml")},
        "local_models": LOCAL_MODELS,
    }
    if a.models:  # 받기 진행 막대용 파일 크기
        manifest["sizes"] = {k: os.path.getsize(os.path.join(a.models, *k.split("/")))
                             for k in list(manifest["hf"]) + LOCAL_MODELS
                             if os.path.isfile(os.path.join(a.models, *k.split("/")))}
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    print("완료:", out)


if __name__ == "__main__":
    main()
