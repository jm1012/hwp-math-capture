"""인식 엔진 묶음 (모두 무료 오픈소스, CPU 에서 onnxruntime 으로 동작)

- 수식 한 개:   Pix2Text MFR  → LaTeX
- 지문(글자+수식): Pix2Text MFD(수식 위치) + PaddleOCR 한국어 + MFR  → 문단 목록
  (+ PP-DocLayout 으로 그림·그래프·표를 찾아 그림으로 잘라 넣음)
"""
from __future__ import annotations

import os
import threading

from PIL import Image, ImageOps


class Recognizer:
    def __init__(self):
        self.mfr = None
        self.passage = None
        self._lock = threading.Lock()
        self.ready = threading.Event()
        self.error: Exception | None = None

    def load_async(self):
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        try:
            import models
            miss = models.missing()
            if miss:
                raise FileNotFoundError(f"모델 파일이 없습니다 ({models.model_dir()}): {', '.join(miss)}\n"
                                        "소스에서 실행 중이면 'python models.py' 로 받으세요.")
            from mfd import MFD
            from mfr import MFR
            from passage import PassageReader
            self.mfr = MFR(models.path("mfr"))
            figures = None
            if os.path.isfile(models.path("layout/pp-doclayout-plus-l.onnx")):
                try:
                    from figures import FigureDetector
                    figures = FigureDetector(models.path("layout/pp-doclayout-plus-l.onnx"))
                except Exception:  # noqa: BLE001  그림 찾기 모델을 못 불러와도 글자·수식은 동작
                    figures = None
            self.passage = PassageReader(
                MFD(models.path("mfd/pix2text-mfd-1.5.onnx")), self.mfr,
                models.path("ocr/det.onnx"), models.path("ocr/rec_korean.onnx"),
                models.path("ocr/rec_korean_dict.txt"), figures=figures)
        except Exception as e:  # noqa: BLE001
            self.error = e
        finally:
            self.ready.set()

    def _wait(self):
        self.ready.wait()
        if self.error:
            raise RuntimeError(f"인식 모델을 불러오지 못했습니다: {self.error}")

    @staticmethod
    def _prepare(img: Image.Image) -> Image.Image:
        img = img.convert("RGB")
        # 어두운 배경(다크 모드 등)이면 반전
        gray = ImageOps.grayscale(img)
        if sum(gray.resize((16, 16)).getdata()) / 256 < 110:
            img = ImageOps.invert(img)
        return img

    def recognize(self, img: Image.Image) -> str:
        """수식 한 개 → LaTeX"""
        from latex_fix import clean_latex
        self._wait()
        with self._lock:
            return clean_latex(self.mfr([self._prepare(img)])[0])

    def recognize_full(self, img: Image.Image) -> tuple[str, str]:
        """수식 한 개 → (LaTeX, 뒤에 글자로 붙일 것).
        수식 인식기는 네모 칸 (가) 를 \\fbox{(7♯)} 로, 점선 뒤 원문자 ㉠ 을 \\odot 로 읽으므로
        그림에서 네모 칸·원문자를 따로 찾아 바꿔 넣는다. 원문자는 "…… ㉠" 글자로 수식 뒤에 붙인다."""
        from latex_fix import clean_latex
        self._wait()
        with self._lock:
            p = self._prepare(img)
            latex = clean_latex(self.mfr([p])[0])
            try:
                return fix_formula_marks(self.passage, p, latex)
            except Exception:  # noqa: BLE001  못 찾으면 인식기 결과 그대로
                return latex, ""

    def read_passage(self, img: Image.Image, figures: bool = True) -> list[list[tuple[str, object]]]:
        """글자+수식 지문 → 문단 목록 [[("text", …), ("math", LaTeX), ("image", passage.Figure), …], …]
        figures=False 면 그림·표 찾기를 건너뜀 (그림 속 글자도 예전처럼 읽힘)"""
        self._wait()
        with self._lock:
            return self.passage(self._prepare(img), figures=figures)


from formula_marks import fix_formula_marks  # noqa: E402
