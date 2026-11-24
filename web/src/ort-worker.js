// 모델 계산 워커: onnxruntime-web (WebGPU, 안 되면 WASM).
// 파이썬 워커(py-worker.js)가 MessagePort 로 요청을 보내고 Atomics.wait 로 기다리면,
// 결과를 SharedArrayBuffer 에 써 넣고 Atomics.notify 로 깨운다.
import * as ort from './vendor/ort/ort.webgpu.min.mjs';

ort.env.wasm.wasmPaths = new URL('./vendor/ort/', import.meta.url).href;
ort.env.logLevel = 'error';

let ctl, data, port, cfg;
const sessions = new Map();
let nextSid = 1;
const DT = { float32: Float32Array, int64: BigInt64Array, int32: Int32Array, uint8: Uint8Array, int8: Int8Array,
  float64: Float64Array, bool: Uint8Array };
const stats = {}; // 모델별 계산 시간 (속도 측정용)

async function modelBytes(key) {
  const url = cfg.urls[key];
  if (!url) throw new Error('모르는 모델: ' + key);
  const cache = await caches.open(cfg.cacheName);
  let res = await cache.match(url);
  if (!res) res = await fetch(url);
  if (!res.ok) throw new Error('모델을 읽지 못함: ' + key);
  return new Uint8Array(await res.arrayBuffer());
}

function epFor(key) {
  const want = (cfg.ep && cfg.ep[key]) || cfg.defaultEp || 'wasm';
  return want === 'webgpu' && cfg.webgpu ? ['webgpu', 'wasm'] : ['wasm'];
}

async function makeSession(key) {
  const eps = epFor(key);
  const t0 = performance.now();
  const s = await ort.InferenceSession.create(await modelBytes(key), {
    executionProviders: eps, graphOptimizationLevel: 'all', logSeverityLevel: 3,
  });
  stats[key] = stats[key] || { runs: 0, ms: 0, load: 0, ep: eps[0] };
  stats[key].load += performance.now() - t0;
  return { s, eps };
}

// 파이썬이 준비되는 동안(몇 초) 모델을 미리 불러 둔다. 파이썬이 같은 모델을 처음 부르면 이것을 넘겨줌
const early = new Map();

async function create(req) {
  let got = null;
  if (early.has(req.key)) {
    const p = early.get(req.key);
    early.delete(req.key);
    got = await p; // 미리 불러오다 실패했으면 null → 아래에서 다시
  }
  const { s, eps } = got || await makeSession(req.key);
  const sid = nextSid++;
  sessions.set(sid, { s, key: req.key });
  return [{ sid, inputs: s.inputNames, outputs: s.outputNames, ep: eps[0] }, []];
}

async function run(req, buffers) {
  const ent = sessions.get(req.sid);
  if (!ent) throw new Error('세션 없음');
  const feeds = {};
  req.feeds.forEach((f, i) => {
    const T = DT[f.dtype];
    if (!T) throw new Error('지원하지 않는 자료형: ' + f.dtype);
    const b = buffers[i];
    const arr = new T(b.buffer, b.byteOffset, b.byteLength / T.BYTES_PER_ELEMENT);
    feeds[f.name] = new ort.Tensor(f.dtype, arr, f.dims);
  });
  const t0 = performance.now();
  const out = await ent.s.run(feeds, req.outputs);
  const st = stats[ent.key];
  st.runs += 1;
  st.ms += performance.now() - t0;
  const heads = [], bins = [];
  let off = 0;
  for (const name of req.outputs) {
    const t = out[name];
    let d = t.data;
    if (t.location && t.location !== 'cpu') d = await t.getData();
    const bytes = new Uint8Array(d.buffer, d.byteOffset, d.byteLength);
    heads.push({ name, dtype: t.type, dims: t.dims.map(Number), offset: off });
    bins.push(bytes);
    off += Math.ceil(bytes.byteLength / 8) * 8;
  }
  for (const k in feeds) feeds[k].dispose?.();
  for (const k in out) out[k].dispose?.();
  return [{ outputs: heads }, bins];
}

// 결과 쓰기: [머리 길이 u32][머리 JSON][8바이트 맞춤][자료]
function reply(head, bins) {
  const hb = new TextEncoder().encode(JSON.stringify(head));
  const start = Math.ceil((4 + hb.byteLength) / 8) * 8;
  let total = start;
  const offs = [];
  for (const b of bins) { offs.push(total); total += Math.ceil(b.byteLength / 8) * 8; }
  if (total > data.byteLength) {
    if (!data.growable || total > data.maxByteLength) throw new Error('결과가 너무 큼: ' + total);
    data.grow(Math.min(data.maxByteLength, Math.max(total, data.byteLength * 2)));
  }
  const u8 = new Uint8Array(data);
  new DataView(data).setUint32(0, hb.byteLength, true);
  u8.set(hb, 4);
  bins.forEach((b, i) => u8.set(b, offs[i]));
  Atomics.store(ctl, 1, start);
  Atomics.store(ctl, 2, total);
  Atomics.store(ctl, 0, 1);
  Atomics.notify(ctl, 0);
}

async function onRequest(ev) {
  const { head, buffers } = ev.data;
  const req = JSON.parse(head);
  try {
    const [h, bins] = req.op === 'create' ? await create(req) : await run(req, buffers);
    reply(h, bins);
  } catch (e) {
    try { reply({ error: String(e && e.message || e) }, []); } catch (e2) {
      Atomics.store(ctl, 1, -1); Atomics.store(ctl, 0, 1); Atomics.notify(ctl, 0);
    }
  }
}

self.onmessage = async (ev) => {
  const m = ev.data;
  if (m.type === 'init') {
    ctl = new Int32Array(m.ctl);
    data = m.data;
    cfg = m.cfg;
    cfg.webgpu = false;
    if (cfg.defaultEp === 'webgpu' || Object.values(cfg.ep || {}).includes('webgpu')) {
      try { cfg.webgpu = !!(navigator.gpu && await navigator.gpu.requestAdapter()); } catch (e) { cfg.webgpu = false; }
    }
    if (cfg.numThreads) ort.env.wasm.numThreads = cfg.numThreads;
    port = m.port;
    port.onmessage = onRequest;
    self.postMessage({ type: 'ready', webgpu: cfg.webgpu, threads: ort.env.wasm.numThreads,
      isolated: self.crossOriginIsolated });
    // 하나씩 차례로 (동시에 만들면 메모리가 한꺼번에 늘어남)
    let chain = Promise.resolve();
    for (const key of cfg.preload || []) {
      const p = chain.then(() => makeSession(key)).catch(() => null);
      chain = p;
      early.set(key, p);
    }
  } else if (m.type === 'stats') {
    self.postMessage({ type: 'stats', stats });
  }
};
