"""인식 모델 파일 위치와 내려받기.

model/
  mfr/  수식 인식   Pix2Text MFR 1.5 (MIT)          encoder_model.onnx, decoder_model.onnx, tokenizer.json
  mfd/  수식 위치   Pix2Text MFD 1.5 (MIT / AGPL-3.0) pix2text-mfd-1.5.onnx
  ocr/  한글 OCR   PaddleOCR PP-OCRv5 (Apache-2.0)  det.onnx, rec_korean.onnx, rec_korean_dict.txt
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
}


def model_dir() -> str:
    """실행 파일 옆 model 폴더, 없으면 소스 폴더(app)의 model 폴더."""
    cands = [os.path.join(os.path.dirname(sys.executable), "model")]
    base = getattr(sys, "_MEIPASS", None)
    if base:
        cands.append(os.path.join(base, "model"))
    cands.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "model"))
    for c in cands:
        if os.path.isfile(os.path.join(c, "mfr", "encoder_model.onnx")):
            return c
    return cands[-1]


def path(rel: str) -> str:
    return os.path.join(model_dir(), *rel.split("/"))


def missing(d: str | None = None) -> list[str]:
    d = d or model_dir()
    need = [k for k in FILES if not k.endswith(".yml")] + ["ocr/rec_korean_dict.txt"]
    return [k for k in need if not os.path.isfile(os.path.join(d, *k.split("/")))]


def download(d: str | None = None, log=print) -> str:
    """빠진 모델 파일을 Hugging Face 에서 받는다 (약 230MB)."""
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


if __name__ == "__main__":
    print("모델 폴더:", download())
