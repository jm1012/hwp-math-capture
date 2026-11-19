"""인식 모델 파일 위치와 내려받기.

model/
  mfr/  수식 인식   Pix2Text MFR 1.5 (MIT)          encoder_model.onnx, decoder_model.onnx, tokenizer.json
                                                  + prepare() 가 만드는 encoder_int8.onnx, decoder_kv.npz (속도용)
  mfd/  수식 위치   Pix2Text MFD 1.5 (MIT / AGPL-3.0) pix2text-mfd-1.5.onnx
  ocr/  한글 OCR   PaddleOCR PP-OCRv5 (Apache-2.0)  det.onnx, rec_korean.onnx, rec_korean_dict.txt
  layout/ 그림·표 위치  PP-DocLayout_plus-L (Apache-2.0)  pp-doclayout-plus-l.onnx  (없으면 그림 처리만 꺼짐)
"""
from __future__ import annotations

import os
import sys

HF = "https://huggingface.co"
FILES = {
    "mfr/encoder_model.onnx": "breezedeus/pix2text-mfr-1.5/resolve/main/encoder_model.onnx",
    "mfr/decoder_model.onnx": "breezedeus/pix2text-mfr-1.5/resolve/main/decoder_model.onnx",
    "mfr/tokenizer.json": "breezedeus/pix2text-mfr-1.5/resolve/main/tokenizer.json",
    "mfd/pix2text-mfd-1.5.onnx": "breezedeus/pix2text-mfd-1.5/resolve/main/pix2text-mfd-1.5.onnx",
    "ocr/det.onnx": "PaddlePaddle/PP-OCRv5_mobile_det_onnx/resolve/main/inference.onnx",
    "ocr/rec_korean.onnx": "PaddlePaddle/korean_PP-OCRv5_mobile_rec_onnx/resolve/main/inference.onnx",
    "ocr/rec_korean.yml": "PaddlePaddle/korean_PP-OCRv5_mobile_rec_onnx/resolve/main/inference.yml",
    "layout/pp-doclayout-plus-l.onnx": "PaddlePaddle/PP-DocLayout_plus-L_onnx/resolve/main/inference.onnx",
}
# 없어도 앱이 도는 파일 (해당 기능만 꺼짐)
OPTIONAL = {"layout/pp-doclayout-plus-l.onnx"}


def model_dir() -> str:
    """실행 파일 옆 model 폴더, 없으면 소스 폴더(app)의 model 폴더."""
    cands = [os.path.join(os.path.dirname(sys.executable), "model")]
    base = getattr(sys, "_MEIPASS", None)
    if base:
        cands.append(os.path.join(base, "model"))
    cands.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "model"))
    for c in cands:
        if os.path.isfile(os.path.join(c, "mfr", "tokenizer.json")):
            return c
    return cands[-1]


def path(rel: str) -> str:
    return os.path.join(model_dir(), *rel.split("/"))


# 실행에는 둘 중 하나만 있으면 됨 (배포판은 빠른 쪽만 넣음)
ALT = {"mfr/encoder_model.onnx": "mfr/encoder_int8.onnx", "mfr/decoder_model.onnx": "mfr/decoder_kv.npz"}


def missing(d: str | None = None, for_run: bool = True) -> list[str]:
    d = d or model_dir()
    has = lambda k: os.path.isfile(os.path.join(d, *k.split("/")))  # noqa: E731
    need = [k for k in FILES if not k.endswith(".yml") and k not in OPTIONAL] + ["ocr/rec_korean_dict.txt"]
    return [k for k in need if not has(k) and not (for_run and k in ALT and has(ALT[k]))]


def download(d: str | None = None, log=print) -> str:
    """빠진 모델 파일을 Hugging Face 에서 받는다 (약 360MB)."""
    import urllib.request
    d = d or os.path.join(os.path.dirname(os.path.abspath(__file__)), "model")
    for rel, url in FILES.items():
        dst = os.path.join(d, *rel.split("/"))
        if os.path.isfile(dst) or (rel.endswith(".yml") and os.path.isfile(dst[:-4] + "_dict.txt")):
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        log(f"받는 중: {rel}")
        urllib.request.urlretrieve(f"{HF}/{url}", dst + ".part")
        os.replace(dst + ".part", dst)
    yml = os.path.join(d, "ocr", "rec_korean.yml")
    dic = os.path.join(d, "ocr", "rec_korean_dict.txt")
    if os.path.isfile(yml) and not os.path.isfile(dic):
        import yaml
        with open(yml, encoding="utf-8") as f:
            chars = yaml.safe_load(f)["PostProcess"]["character_dict"]
        with open(dic, "w", encoding="utf-8") as f:
            f.write("\n".join(chars) + "\n")
        os.remove(yml)
    return d


def prepare(d: str | None = None, log=print) -> str:
    """속도용 파일을 만든다 (빌드할 때 한 번, onnx 패키지 필요). 없어도 앱은 원래 방식으로 동작."""
    from mfr import export_decoder_npz, quantize_encoder
    d = d or model_dir()
    m = os.path.join(d, "mfr")
    if not os.path.isfile(os.path.join(m, "decoder_kv.npz")):
        log("만드는 중: mfr/decoder_kv.npz")
        export_decoder_npz(os.path.join(m, "decoder_model.onnx"), os.path.join(m, "decoder_kv.npz"))
    if not os.path.isfile(os.path.join(m, "encoder_int8.onnx")):
        log("만드는 중: mfr/encoder_int8.onnx")
        quantize_encoder(os.path.join(m, "encoder_model.onnx"), os.path.join(m, "encoder_int8.onnx"))
    return d


if __name__ == "__main__":
    print("모델 폴더:", prepare(download()))
