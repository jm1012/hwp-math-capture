"""브라우저용 tokenizers 대체 모듈: 수식 인식(MFR)이 쓰는 Tokenizer.from_file / decode 만.

MFR 1.5 의 tokenizer.json 은 ByteLevel BPE 라서, 글자 조각을 이어 붙인 뒤 GPT-2 바이트 표로 되돌리면
Rust tokenizers 의 decode(skip_special_tokens=True) 와 같은 결과가 나온다.
"""
from __future__ import annotations

import json


def _byte_table():
    bs = list(range(ord("!"), ord("~") + 1)) + list(range(ord("¡"), ord("¬") + 1)) + list(range(ord("®"), ord("ÿ") + 1))
    cs = bs[:]
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b)
            cs.append(256 + n)
            n += 1
    return {chr(c): b for b, c in zip(bs, cs)}


class Tokenizer:
    def __init__(self, data: dict):
        self.id2tok = {i: t for t, i in data["model"]["vocab"].items()}
        self.special = set()
        for a in data.get("added_tokens", []):
            self.id2tok[a["id"]] = a["content"]
            if a.get("special"):
                self.special.add(a["id"])
        dec = data.get("decoder") or {}
        if dec.get("type") != "ByteLevel":
            raise ValueError("ByteLevel 디코더만 지원")
        self._bytes = _byte_table()

    @classmethod
    def from_file(cls, path: str) -> "Tokenizer":
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f))

    def decode(self, ids, skip_special_tokens: bool = True) -> str:
        toks = [self.id2tok.get(int(i), "") for i in ids if not (skip_special_tokens and int(i) in self.special)]
        b = bytearray()
        for t in toks:
            for ch in t:
                if ch in self._bytes:
                    b.append(self._bytes[ch])
                else:
                    b += ch.encode("utf-8")
        return b.decode("utf-8", errors="replace")
