"""수식 이미지 → LaTeX (Pix2Text MFR 1.5, ONNX). torch 없이 onnxruntime + tokenizers 만 쓴다.

속도를 위해 model/mfr 에 다음 파일이 있으면 쓴다 (models.py prepare 가 만듦, 없으면 원래 방식):
- encoder_int8.onnx  : 인코더 int8 양자화 (정확도 같고 약 1.5배 빠름)
- decoder_kv.npz     : 디코더 가중치. 앞 글자 계산을 저장해 두는 KV 캐시로 numpy 에서 직접 계산 (결과 동일)
"""
from __future__ import annotations

import os

import numpy as np
from PIL import Image, ImageOps


def _ln(x, w, b, eps=1e-5):
    m = x.mean(-1, keepdims=True)
    v = ((x - m) ** 2).mean(-1, keepdims=True)
    return (x - m) / np.sqrt(v + eps) * w + b


class KVDecoder:
    """TrOCR 디코더 (6층, d=256, 8헤드, post-LN) 를 KV 캐시로 한 글자씩 계산한다."""
    LAYERS, D, HEADS = 6, 256, 8
    ATTN = ("self_attn", "encoder_attn")
    PROJ = ("q_proj", "k_proj", "v_proj", "out_proj")
    LNS = ("self_attn_layer_norm", "encoder_attn_layer_norm", "final_layer_norm")

    def __init__(self, npz_path: str):
        w = np.load(npz_path)
        self.emb, self.pos = w["embed_tokens"], w["embed_positions"]
        self.lne = (w["layernorm_embedding.w"], w["layernorm_embedding.b"])
        self.out = w["output_projection"]
        self.L = []
        for i in range(self.LAYERS):
            g = lambda k: (w[f"{i}.{k}.w"], w[f"{i}.{k}.b"])  # noqa: E731
            L = {f"{a}.{p}": g(f"{a}.{p}") for a in self.ATTN for p in self.PROJ}
            L.update({k: g(k) for k in ("fc1", "fc2") + self.LNS})
            self.L.append(L)
        self.scale = float(np.sqrt(self.D))  # python float: numpy 스칼라면 float64 로 바뀌어 느려짐
        self.hd = self.D // self.HEADS

    def _heads(self, x):  # (B,T,D) → (B,H,T,d)
        return x.reshape(x.shape[0], x.shape[1], self.HEADS, self.hd).transpose(0, 2, 1, 3)

    def start(self, enc):
        """인코더 출력에 대한 cross-attention K/V 를 한 번만 계산"""
        st = {"t": 0, "ck": [], "cv": [], "sk": [None] * self.LAYERS, "sv": [None] * self.LAYERS}
        for L in self.L:
            w, b = L["encoder_attn.k_proj"]; st["ck"].append(self._heads(enc @ w + b))
            w, b = L["encoder_attn.v_proj"]; st["cv"].append(self._heads(enc @ w + b))
        return st

    def _attn(self, L, a, x, k, v):
        w, b = L[a + ".q_proj"]
        q = self._heads(x @ w + b) * self.hd ** -0.5
        s = q @ k.transpose(0, 1, 3, 2)
        s = np.exp(s - s.max(-1, keepdims=True)); s /= s.sum(-1, keepdims=True)
        o = (s @ v).transpose(0, 2, 1, 3).reshape(x.shape[0], 1, self.D)
        w, b = L[a + ".out_proj"]
        return o @ w + b

    def step(self, st, ids):
        """ids (B,) → 다음 글자 logits (B, V)"""
        t = st["t"]
        x = self.emb[ids][:, None, :] * self.scale + self.pos[t + 2][None, None]  # 위치 임베딩은 2칸 밀림
        x = _ln(x, *self.lne)
        for i, L in enumerate(self.L):
            w, b = L["self_attn.k_proj"]; k = self._heads(x @ w + b)
            w, b = L["self_attn.v_proj"]; v = self._heads(x @ w + b)
            st["sk"][i] = k if st["sk"][i] is None else np.concatenate([st["sk"][i], k], 2)
            st["sv"][i] = v if st["sv"][i] is None else np.concatenate([st["sv"][i], v], 2)
            x = _ln(x + self._attn(L, "self_attn", x, st["sk"][i], st["sv"][i]), *L["self_attn_layer_norm"])
            x = _ln(x + self._attn(L, "encoder_attn", x, st["ck"][i], st["cv"][i]), *L["encoder_attn_layer_norm"])
            w, b = L["fc1"]; h = np.maximum(x @ w + b, 0)
            w, b = L["fc2"]
            x = _ln(x + h @ w + b, *L["final_layer_norm"])
        st["t"] = t + 1
        return (x @ self.out)[:, 0]

    def keep(self, st, idx):
        """끝난 줄은 빼고 남은 줄만 계속 계산"""
        for k in ("ck", "cv", "sk", "sv"):
            st[k] = [a[idx] for a in st[k]]


def export_decoder_npz(onnx_path: str, npz_path: str):
    """decoder_model.onnx 의 가중치를 KVDecoder 용 npz 로 꺼낸다 (빌드할 때 한 번, onnx 패키지 필요)."""
    import onnx
    from onnx import numpy_helper
    m = onnx.load(onnx_path)
    init = {i.name: numpy_helper.to_array(i).astype(np.float32) for i in m.graph.initializer}
    mat = {}  # MatMul 가중치는 이름이 없어서 노드 이름으로 찾음: /decoder/decoder/layers.0/self_attn/q_proj/MatMul
    for n in m.graph.node:
        if n.op_type == "MatMul":
            w = [i for i in n.input if i in init]
            if w:
                key = n.name.replace("/decoder/decoder/", "").replace("/decoder/", "").replace("/MatMul", "")
                mat[key] = init[w[0]]
    p = "decoder.model.decoder."
    out = {"embed_tokens": init[p + "embed_tokens.weight"], "embed_positions": init[p + "embed_positions.weight"],
           "layernorm_embedding.w": init[p + "layernorm_embedding.weight"],
           "layernorm_embedding.b": init[p + "layernorm_embedding.bias"],
           "output_projection": mat["output_projection"]}
    for i in range(KVDecoder.LAYERS):
        q = f"{p}layers.{i}."
        for a in KVDecoder.ATTN:
            for pr in KVDecoder.PROJ:
                out[f"{i}.{a}.{pr}.w"] = mat[f"layers.{i}/{a}/{pr}"]
                out[f"{i}.{a}.{pr}.b"] = init[f"{q}{a}.{pr}.bias"]
        for f in ("fc1", "fc2"):
            out[f"{i}.{f}.w"] = mat[f"layers.{i}/{f}"]; out[f"{i}.{f}.b"] = init[f"{q}{f}.bias"]
        for ln in KVDecoder.LNS:
            out[f"{i}.{ln}.w"] = init[f"{q}{ln}.weight"]; out[f"{i}.{ln}.b"] = init[f"{q}{ln}.bias"]
    tmp = npz_path + ".part.npz"
    np.savez(tmp, **out)
    os.replace(tmp, npz_path)


def quantize_encoder(onnx_path: str, out_path: str):
    """인코더 int8 동적 양자화 (빌드할 때 한 번)."""
    from onnxruntime.quantization import QuantType, quantize_dynamic
    tmp = out_path + ".part.onnx"
    quantize_dynamic(onnx_path, tmp, weight_type=QuantType.QInt8)
    os.replace(tmp, out_path)


class MFR:
    BOS, EOS, PAD = 1, 2, 0

    def __init__(self, model_dir: str, max_len: int = 400):
        import onnxruntime as ort
        from tokenizers import Tokenizer
        opt = ort.SessionOptions()
        opt.log_severity_level = 3
        prov = ["CPUExecutionProvider"]
        enc = os.path.join(model_dir, "encoder_int8.onnx")
        if not os.path.isfile(enc):
            enc = os.path.join(model_dir, "encoder_model.onnx")
        self.enc = ort.InferenceSession(enc, opt, providers=prov)
        npz = os.path.join(model_dir, "decoder_kv.npz")
        self.kv = KVDecoder(npz) if os.path.isfile(npz) else None
        self.dec = None if self.kv else ort.InferenceSession(
            os.path.join(model_dir, "decoder_model.onnx"), opt, providers=prov)
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
        seqs = self._greedy_kv(h) if self.kv else self._greedy_full(h)
        return [self.tok.decode(s, skip_special_tokens=True) for s in seqs]

    def _greedy_kv(self, h):
        n = len(h)
        st = self.kv.start(h)
        alive = list(range(n))
        cur = np.full(n, self.BOS, dtype=np.int64)
        seqs: list[list[int]] = [[] for _ in range(n)]
        for _ in range(self.max_len):
            nxt = self.kv.step(st, cur).argmax(-1)
            keep = [j for j, t in enumerate(nxt) if t != self.EOS]
            for j in keep:
                seqs[alive[j]].append(int(nxt[j]))
            if not keep:
                break
            if len(keep) < len(alive):
                self.kv.keep(st, np.array(keep))
                alive = [alive[j] for j in keep]
            cur = nxt[keep].astype(np.int64)
        return seqs

    def _greedy_full(self, h):
        n = len(h)
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
        return [[int(t) for t in row if t not in (self.EOS, self.PAD)] for row in ids[:, 1:]]
