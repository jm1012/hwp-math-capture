"""수식 이미지 → LaTeX (Pix2Text MFR 1.5, ONNX). torch 없이 onnxruntime + tokenizers 만 쓴다."""
from __future__ import annotations

import os

import numpy as np
from PIL import Image, ImageOps


class MFR:
    BOS, EOS, PAD = 1, 2, 0

    def __init__(self, model_dir: str, max_len: int = 400):
        import onnxruntime as ort
        from tokenizers import Tokenizer
        opt = ort.SessionOptions()
        opt.log_severity_level = 3
        prov = ["CPUExecutionProvider"]
        self.enc = ort.InferenceSession(os.path.join(model_dir, "encoder_model.onnx"), opt, providers=prov)
        self.dec = ort.InferenceSession(os.path.join(model_dir, "decoder_model.onnx"), opt, providers=prov)
        self.tok = Tokenizer.from_file(os.path.join(model_dir, "tokenizer.json"))
        self.max_len = max_len

    @staticmethod
    def _pre(img: Image.Image) -> np.ndarray:
        img = ImageOps.expand(img.convert("RGB"), border=6, fill="white").resize((384, 384), Image.BICUBIC)
        x = np.asarray(img, dtype=np.float32) / 255.0
        return ((x - 0.5) / 0.5).transpose(2, 0, 1)

    def __call__(self, imgs: list[Image.Image], batch: int = 4) -> list[str]:
        out: list[str] = []
        for i in range(0, len(imgs), batch):
            out += self._run(imgs[i:i + batch])
        return out

    def _run(self, imgs):
        if not imgs:
            return []
        h = self.enc.run(None, {"pixel_values": np.stack([self._pre(i) for i in imgs])})[0]
        n = len(imgs)
        ids = np.full((n, 1), self.BOS, dtype=np.int64)
        done = np.zeros(n, dtype=bool)
        for _ in range(self.max_len):
            logits = self.dec.run(None, {"input_ids": ids, "encoder_hidden_states": h})[0][:, -1]
            nxt = logits.argmax(-1)
            nxt[done] = self.PAD
            ids = np.concatenate([ids, nxt[:, None]], 1)
            done |= nxt == self.EOS
            if done.all():
                break
        res = []
        for row in ids[:, 1:]:
            toks = [int(t) for t in row if t not in (self.EOS, self.PAD)]
            res.append(self.tok.decode(toks, skip_special_tokens=True))
        return res
