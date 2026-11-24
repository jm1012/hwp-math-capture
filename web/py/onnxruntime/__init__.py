"""브라우저용 onnxruntime 대체 모듈.

app 코드(mfd, mfr, figures)와 rapidocr 가 부르는 onnxruntime API 중 쓰는 부분만 같은 모양으로 만든다.
실제 계산은 다른 웹 워커의 onnxruntime-web(WebGPU, 안 되면 WASM)이 하고, 이 워커는 결과가 올 때까지
SharedArrayBuffer 로 기다린다 (py-worker.js 의 ortBridge).
모델 파일 경로는 model 폴더 기준 이름("ocr/det.onnx")으로 바꿔 넘긴다. 실제 모델은 브라우저 저장소(Cache)에 있음.
"""
from __future__ import annotations

import json
import os

import numpy as np

__version__ = "web"

_DT = {"float32": np.float32, "int64": np.int64, "int32": np.int32, "uint8": np.uint8, "int8": np.int8,
       "float64": np.float64, "bool": np.bool_}


class GraphOptimizationLevel:
    ORT_DISABLE_ALL = 0
    ORT_ENABLE_BASIC = 1
    ORT_ENABLE_EXTENDED = 2
    ORT_ENABLE_ALL = 99


class SessionOptions:
    def __init__(self):
        self.log_severity_level = 2
        self.intra_op_num_threads = 0
        self.inter_op_num_threads = 0
        self.enable_cpu_mem_arena = True
        self.graph_optimization_level = GraphOptimizationLevel.ORT_ENABLE_ALL


class RunOptions:
    pass


def get_available_providers():
    return ["CPUExecutionProvider"]


def get_device():
    return "CPU"


class NodeArg:
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f"NodeArg(name={self.name!r})"


class ModelMetadata:
    def __init__(self, meta):
        self.custom_metadata_map = dict(meta or {})


MODEL_ROOT = None  # webapi 가 정함 (app/model 폴더)


def _key(path) -> str:
    p = os.path.abspath(str(path))
    root = MODEL_ROOT or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "model")
    if p.startswith(root + os.sep):
        return p[len(root) + 1:].replace(os.sep, "/")
    return p


def _call(req: dict, buffers=()):
    from js import ortBridge  # py-worker.js
    from pyodide.ffi import to_js
    res = ortBridge.call(json.dumps(req), to_js([memoryview(b) for b in buffers]))
    head = json.loads(res[0])
    if "error" in head:
        raise RuntimeError("onnxruntime-web: " + head["error"])
    data = res[1].to_bytes() if len(res) > 1 and res[1] is not None else b""
    return head, data


class InferenceSession:
    def __init__(self, path, sess_options=None, providers=None, **kw):
        self._key = _key(path)
        head, _ = _call({"op": "create", "key": self._key})
        self._sid = head["sid"]
        self._inputs = [NodeArg(n) for n in head["inputs"]]
        self._outputs = [NodeArg(n) for n in head["outputs"]]
        self._meta = head.get("meta") or {}
        self._ep = head.get("ep", "wasm")

    def get_inputs(self):
        return list(self._inputs)

    def get_outputs(self):
        return list(self._outputs)

    def get_providers(self):
        return ["CPUExecutionProvider"]

    def get_modelmeta(self):
        return ModelMetadata(self._meta)

    def run(self, output_names, input_feed, run_options=None):
        names = list(output_names) if output_names else [o.name for o in self._outputs]
        feeds, bufs = [], []
        for name, arr in input_feed.items():
            a = np.ascontiguousarray(arr)
            if a.dtype == np.float64:
                a = a.astype(np.float32)
            feeds.append({"name": name, "dtype": str(a.dtype), "dims": [int(d) for d in a.shape]})
            bufs.append(a.tobytes())
        head, data = _call({"op": "run", "sid": self._sid, "outputs": names, "feeds": feeds}, bufs)
        out = []
        for t in head["outputs"]:
            dt = np.dtype(_DT[t["dtype"]])
            n = int(np.prod(t["dims"])) if t["dims"] else 1
            a = np.frombuffer(data, dtype=dt, count=n, offset=t["offset"]).reshape(t["dims"]).copy()
            out.append(a)
        return out
