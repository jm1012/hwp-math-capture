"""브라우저용 pypdfium2 대체 모듈: pdf_layout 이 쓰는 부분만 (쪽 수, 쪽 그림, 글자와 글자 상자).

PDFium 을 wasm 으로 빌드한 @embedpdf/pdfium 을 py-worker.js 의 pdfHelper 로 부른다 (exe 의 pypdfium2 와 같은 엔진).
"""
from __future__ import annotations

import math

from PIL import Image


def _helper():
    from js import pdfHelper  # py-worker.js
    return pdfHelper


class PdfDocument:
    def __init__(self, src, password=None):
        if isinstance(src, (bytes, bytearray, memoryview)):
            data = bytes(src)
        else:
            with open(src, "rb") as f:
                data = f.read()
        from pyodide.ffi import to_js
        self._h = _helper().open(to_js(memoryview(data)))
        if self._h < 0:
            raise RuntimeError("PDF를 열지 못했습니다 (암호가 걸렸거나 손상된 파일)")
        self._n = int(_helper().pageCount(self._h))

    def __len__(self):
        return self._n

    def __getitem__(self, i):
        if i < 0:
            i += self._n
        if not 0 <= i < self._n:
            raise IndexError(i)
        return PdfPage(self, i)

    def close(self):
        if self._h is not None and self._h >= 0:
            _helper().close(self._h)
        self._h = None

    def __del__(self):
        try:
            self.close()
        except Exception:  # noqa: BLE001
            pass


class PdfPage:
    def __init__(self, doc, i):
        self.doc, self.i = doc, i
        sz = _helper().pageSize(doc._h, i)
        self._w, self._h = float(sz[0]), float(sz[1])

    def get_width(self):
        return self._w

    def get_height(self):
        return self._h

    def get_size(self):
        return self._w, self._h

    def render(self, scale=1, **kw):
        w, h = math.ceil(self._w * scale), math.ceil(self._h * scale)
        res = _helper().render(self.doc._h, self.i, w, h)
        return PdfBitmap(Image.frombytes("RGB", (w, h), res.to_bytes()))

    def get_textpage(self):
        return PdfTextPage(self)


class PdfBitmap:
    def __init__(self, img):
        self._img = img

    def to_pil(self):
        return self._img


class PdfTextPage:
    def __init__(self, page):
        r = _helper().chars(page.doc._h, page.i)
        self._codes = list(r.codes.to_py())
        b = list(r.boxes.to_py())
        self._boxes = [tuple(b[4 * k:4 * k + 4]) for k in range(len(self._codes))]

    def count_chars(self):
        return len(self._codes)

    def get_text_range(self, index=0, count=-1, **kw):
        if count < 0:
            count = len(self._codes) - index
        s = []
        for c in self._codes[index:index + count]:
            try:
                s.append(chr(c) if c else "")
            except (ValueError, OverflowError):
                s.append("")
        return "".join(s)

    def get_charbox(self, index, loose=False):
        return self._boxes[index]  # (left, bottom, right, top)

    def close(self):
        pass
