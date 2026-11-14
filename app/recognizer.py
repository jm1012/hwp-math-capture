"""수식 이미지 → LaTeX (texify, 무료 오픈소스 모델, CPU에서 동작)"""
from __future__ import annotations

import threading

from PIL import Image, ImageOps


class Recognizer:
    def __init__(self):
        self._model = None
        self._processor = None
        self._lock = threading.Lock()
        self.ready = threading.Event()
        self.error: Exception | None = None

    def load_async(self):
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        try:
            # 실행파일(.exe)로 묶였거나 옆에 model 폴더가 있으면 그 모델을 오프라인으로 사용
            import os, sys
            base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(sys.argv[0]))
            for cand in (os.path.join(os.path.dirname(sys.executable), "model"), os.path.join(base, "model")):
                if os.path.isfile(os.path.join(cand, "config.json")):
                    os.environ["MODEL_CHECKPOINT"] = cand
                    os.environ["HF_HUB_OFFLINE"] = "1"
                    os.environ["TRANSFORMERS_OFFLINE"] = "1"
                    break
            # texify 0.2.1 과 최신 transformers 를 같이 쓸 때 설정 출력에서 나는 오류 우회
            from transformers import PretrainedConfig
            PretrainedConfig.__repr__ = lambda self: self.__class__.__name__
            from texify.model.model import load_model
            from texify.model.processor import load_processor
            self._model = load_model()
            self._processor = load_processor()
        except Exception as e:  # noqa: BLE001
            self.error = e
        finally:
            self.ready.set()

    @staticmethod
    def _prepare(img: Image.Image) -> Image.Image:
        img = img.convert("RGB")
        # 어두운 배경(다크 모드 등)이면 반전
        gray = ImageOps.grayscale(img)
        if sum(gray.resize((16, 16)).getdata()) / 256 < 110:
            img = ImageOps.invert(img)
        # 여백을 조금 줘야 인식이 안정적
        return ImageOps.expand(img, border=12, fill="white")

    def recognize(self, img: Image.Image) -> str:
        self.ready.wait()
        if self.error:
            raise RuntimeError(f"인식 모델을 불러오지 못했습니다: {self.error}")
        from texify.inference import batch_inference
        with self._lock:
            return batch_inference([self._prepare(img)], self._model, self._processor)[0]


def strip_math(text: str) -> str:
    """texify 출력에서 $$ ... $$ 수식 부분만 꺼낸다. 여러 개면 줄바꿈으로 잇는다."""
    import re
    parts = re.findall(r"\$\$(.+?)\$\$|\$(.+?)\$", text, flags=re.S)
    found = [a or b for a, b in parts]
    return " \\\\ ".join(p.strip() for p in found) if found else text.strip()
