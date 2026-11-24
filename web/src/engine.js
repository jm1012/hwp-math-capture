// 화면 쪽에서 쓰는 엔진: 모델 내려받기(브라우저 저장소에 보관), 두 워커 연결, 요청 보내기.
const CACHE = 'hwp-math-models-v1';

export class Engine {
  constructor() {
    this.ready = false;
    this.pending = new Map();
    this.nextId = 1;
    this.onProgress = null;
    this.onStatus = null;
  }

  static check() {
    const miss = [];
    if (!self.crossOriginIsolated) miss.push('cross-origin isolation');
    if (typeof SharedArrayBuffer === 'undefined') miss.push('SharedArrayBuffer');
    if (!self.caches) miss.push('Cache Storage');
    if (typeof WebAssembly === 'undefined') miss.push('WebAssembly');
    return miss;
  }

  async loadManifest() {
    this.manifest = await (await fetch(new URL('manifest.json', import.meta.url), { cache: 'no-cache' })).json();
    const m = this.manifest;
    const urls = {};
    for (const [k, u] of Object.entries(m.hf)) urls[k] = u;
    for (const k of m.local_models) urls[k] = new URL('models/' + k, import.meta.url).href;
    // 브라우저에서 쓰는 파일 (exe 의 models.missing(for_run) 과 같음: 파생 파일이 있으면 원본 대신)
    const need = ['mfr/encoder_int8.onnx', 'mfr/decoder_kv.npz', 'mfr/tokenizer.json', 'mfd/pix2text-mfd-1.5.onnx',
      'ocr/det.onnx', 'ocr/rec_korean.onnx', 'ocr/rec_korean_dict.txt', 'layout/pp-doclayout-plus-l.onnx',
      'mfr/cross_kv.onnx'];
    this.files = need.map((k) => ({ key: k, url: urls[k] }));
    this.urls = urls;
    return m;
  }

  async missingModels() {
    const c = await caches.open(CACHE);
    const out = [];
    for (const f of this.files) if (!(await c.match(f.url))) out.push(f);
    return out;
  }

  // 빠진 모델을 받아 브라우저 저장소(Cache Storage)에 둔다. onBytes(받은 바이트, 전체 바이트, 파일 이름)
  async download(onBytes) {
    try { await navigator.storage?.persist?.(); } catch (e) { /* 무시 */ }
    const c = await caches.open(CACHE);
    const miss = await this.missingModels();
    const sizes = this.manifest.sizes || {};
    let total = miss.reduce((s, f) => s + (sizes[f.key] || 0), 0);
    let got = 0;
    for (const f of miss) {
      const res = await fetch(f.url, { mode: 'cors' });
      if (!res.ok) throw new Error(`${f.key} 를 받지 못했습니다 (${res.status})`);
      const len = Number(res.headers.get('content-length')) || sizes[f.key] || 0;
      if (!sizes[f.key]) total += len;
      const reader = res.body.getReader();
      const parts = [];
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        parts.push(value);
        got += value.byteLength;
        onBytes?.(got, total, f.key);
      }
      const blob = new Blob(parts);
      await c.put(f.url, new Response(blob, { headers: { 'content-type': 'application/octet-stream', 'content-length': String(blob.size) } }));
    }
  }

  static async clearModels() { await caches.delete(CACHE); }

  async start(opts = {}) {
    const hc = navigator.hardwareConcurrency || 4;
    this.ctl = new SharedArrayBuffer(16);
    let data;
    try { data = new SharedArrayBuffer(32 << 20, { maxByteLength: 1536 << 20 }); } catch (e) { data = new SharedArrayBuffer(512 << 20); }
    this.cancelBuf = new SharedArrayBuffer(4);
    const ch = new MessageChannel();
    this.ort = new Worker(new URL('./ort-worker.js', import.meta.url), { type: 'module' });
    this.py = new Worker(new URL('./py-worker.js', import.meta.url), { type: 'module' });
    const ep = opts.ep || 'auto';
    const cfg = {
      urls: this.urls, cacheName: CACHE, numThreads: opts.numThreads || Math.max(1, Math.min(8, hc - 1)),
      defaultEp: ep === 'wasm' ? 'wasm' : 'webgpu',
      // 입력 크기가 늘 바뀌는 OCR 모델은 WebGPU 에서 오히려 느려서 WASM 으로
      ep: ep === 'wasm' ? {} : { 'ocr/det.onnx': 'wasm', 'ocr/rec_korean.onnx': 'wasm', ...(opts.epPerModel || {}) },
    };
    const ortReady = new Promise((res, rej) => {
      this.ort.onmessage = (e) => { if (e.data.type === 'ready') res(e.data); };
      this.ort.onerror = (e) => rej(new Error('계산 워커를 시작하지 못했습니다: ' + (e.message || '')));
    });
    this.ort.postMessage({ type: 'init', ctl: this.ctl, data, cfg, port: ch.port2 }, [ch.port2]);
    this.ortInfo = await ortReady;
    this.py.onmessage = (e) => this._onPy(e.data);
    this.py.onerror = (e) => { for (const p of this.pending.values()) p.rej(new Error(e.message || '파이썬 워커 오류')); };
    const placeholders = ['mfr/encoder_int8.onnx', 'mfd/pix2text-mfd-1.5.onnx', 'ocr/det.onnx', 'ocr/rec_korean.onnx',
      'layout/pp-doclayout-plus-l.onnx', 'mfr/cross_kv.onnx'];
    const pyFiles = ['mfr/tokenizer.json', 'mfr/decoder_kv.npz', 'ocr/rec_korean_dict.txt'];
    this.setupInfo = await this.call('init', {
      ctl: this.ctl, data, cancel: this.cancelBuf, port: ch.port1, manifest: this.manifest,
      urls: this.urls, cacheName: CACHE, placeholders, pyFiles,
    }, [ch.port1]);
    this.ready = true;
    return { ...this.ortInfo, ...this.setupInfo };
  }

  _onPy(m) {
    if (m.type === 'progress') { this.onProgress?.(m); return; }
    if (m.type === 'status') { this.onStatus?.(m.text); return; }
    if (m.type === 'result') {
      const p = this.pending.get(m.id);
      if (!p) return;
      this.pending.delete(m.id);
      if (m.error) p.rej(new Error(m.error)); else p.res(m.result);
    }
  }

  call(fn, args, transfer) {
    const id = this.nextId++;
    return new Promise((res, rej) => {
      this.pending.set(id, { res, rej });
      this.py.postMessage({ id, fn, args }, transfer || []);
    });
  }

  cancel() { Atomics.store(new Int32Array(this.cancelBuf), 0, 1); }

  stats() {
    return new Promise((res) => {
      const prev = this.ort.onmessage;
      this.ort.onmessage = (e) => { if (e.data.type === 'stats') { this.ort.onmessage = prev; res(e.data.stats); } };
      this.ort.postMessage({ type: 'stats' });
    });
  }
}
