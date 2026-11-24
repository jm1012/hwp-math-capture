// 파이썬 워커: Pyodide 로 exe 와 같은 인식·변환 코드(app/*.py)를 돌린다.
// 모델 계산은 ort-worker.js 에 맡기고 SharedArrayBuffer 로 기다린다 (파이썬 코드는 동기식이므로).
import { loadPyodide } from './vendor/pyodide/pyodide.mjs';
import { init as pdfiumInit } from './vendor/pdfium/index.browser.js';

let py, api, ctl, data, port, cancel, pdfium;
const base = new URL('./', import.meta.url).href;

// ---------------------------------------------------------------- onnxruntime 다리 (web/py/onnxruntime)
self.ortBridge = {
  call(head, buffers) {
    const bufs = [];
    const list = buffers ? Array.from(buffers) : [];
    for (const b of list) bufs.push(new Uint8Array(b)); // 복사 (파이썬 메모리를 넘기지 않음)
    if (buffers && buffers.destroy) buffers.destroy();
    Atomics.store(ctl, 0, 0);
    port.postMessage({ head, buffers: bufs }, bufs.map((b) => b.buffer));
    Atomics.wait(ctl, 0, 0);
    const start = Atomics.load(ctl, 1);
    if (start < 0) return [JSON.stringify({ error: '계산 워커 오류' }), null];
    const total = Atomics.load(ctl, 2);
    const hl = new DataView(data).getUint32(0, true);
    const h = new TextDecoder().decode(new Uint8Array(data, 4, hl).slice());
    return [h, new Uint8Array(data, start, total - start).slice()];
  },
};
self.cancelFlag = () => Atomics.load(cancel, 0);

// ---------------------------------------------------------------- PDFium 다리 (web/py/pypdfium2)
const docs = new Map();
let nextDoc = 1;
self.pdfHelper = {
  open(bytes) {
    const m = pdfium.pdfium;
    const n = bytes.length;
    const ptr = m.wasmExports.malloc(n);
    m.HEAPU8.set(bytes, ptr);
    const doc = pdfium.FPDF_LoadMemDocument(ptr, n, '');
    if (!doc) { m.wasmExports.free(ptr); return -1; }
    const h = nextDoc++;
    docs.set(h, { doc, ptr });
    return h;
  },
  close(h) {
    const d = docs.get(h);
    if (!d) return;
    pdfium.FPDF_CloseDocument(d.doc);
    pdfium.pdfium.wasmExports.free(d.ptr);
    docs.delete(h);
  },
  pageCount(h) { return pdfium.FPDF_GetPageCount(docs.get(h).doc); },
  pageSize(h, i) {
    const page = pdfium.FPDF_LoadPage(docs.get(h).doc, i);
    const r = [pdfium.FPDF_GetPageWidthF(page), pdfium.FPDF_GetPageHeightF(page)];
    pdfium.FPDF_ClosePage(page);
    return r;
  },
  // pypdfium2 PdfPage.render 기본값과 같게: BGR, 흰 바탕, 주석 그림(FPDF_ANNOT) → RGB 바이트
  render(h, i, w, hgt) {
    const m = pdfium.pdfium;
    const page = pdfium.FPDF_LoadPage(docs.get(h).doc, i);
    const bmp = pdfium.FPDFBitmap_CreateEx(w, hgt, 2 /* FPDFBitmap_BGR */, 0, 0);
    pdfium.FPDFBitmap_FillRect(bmp, 0, 0, w, hgt, 0xFFFFFFFF);
    pdfium.FPDF_RenderPageBitmap(bmp, page, 0, 0, w, hgt, 0, 0x01 /* FPDF_ANNOT */);
    const stride = pdfium.FPDFBitmap_GetStride(bmp);
    const buf = pdfium.FPDFBitmap_GetBuffer(bmp);
    const src = m.HEAPU8;
    const out = new Uint8Array(w * hgt * 3);
    for (let y = 0; y < hgt; y++) {
      let s = buf + y * stride, o = y * w * 3;
      for (let x = 0; x < w; x++, s += 3, o += 3) { out[o] = src[s + 2]; out[o + 1] = src[s + 1]; out[o + 2] = src[s]; }
    }
    pdfium.FPDFBitmap_Destroy(bmp);
    pdfium.FPDF_ClosePage(page);
    return out;
  },
  chars(h, i) {
    const m = pdfium.pdfium;
    const page = pdfium.FPDF_LoadPage(docs.get(h).doc, i);
    const tp = pdfium.FPDFText_LoadPage(page);
    const n = Math.max(0, pdfium.FPDFText_CountChars(tp));
    const codes = new Int32Array(n), boxes = new Float64Array(n * 4);
    const p = m.wasmExports.malloc(32);
    for (let k = 0; k < n; k++) {
      codes[k] = pdfium.FPDFText_GetUnicode(tp, k);
      if (pdfium.FPDFText_GetCharBox(tp, k, p, p + 8, p + 16, p + 24)) {
        const f = new Float64Array(m.HEAPU8.buffer, p, 4); // left, right, bottom, top
        boxes[4 * k] = f[0]; boxes[4 * k + 1] = f[2]; boxes[4 * k + 2] = f[1]; boxes[4 * k + 3] = f[3];
      }
    }
    m.wasmExports.free(p);
    pdfium.FPDFText_ClosePage(tp);
    pdfium.FPDF_ClosePage(page);
    return { codes, boxes };
  },
};

// ---------------------------------------------------------------- 준비
async function cached(url, cacheName) {
  const c = await caches.open(cacheName);
  let r = await c.match(url);
  if (!r) r = await fetch(url);
  if (!r.ok) throw new Error('받지 못함: ' + url);
  return new Uint8Array(await r.arrayBuffer());
}

async function init(m) {
  ctl = new Int32Array(m.ctl);
  data = m.data;
  cancel = new Int32Array(m.cancel);
  port = m.port;
  const man = m.manifest;
  const say = (t) => self.postMessage({ type: 'status', text: t });

  say('PDF 엔진 준비 중');
  const wasm = await (await fetch(base + 'vendor/pdfium/pdfium.wasm')).arrayBuffer();
  pdfium = await pdfiumInit({ wasmBinary: wasm });
  pdfium.PDFiumExt_Init();

  say('파이썬 준비 중');
  py = await loadPyodide({ indexURL: base + 'vendor/pyodide/', stdout: (s) => console.log(s), stderr: (s) => console.warn(s) });
  await py.loadPackage(man.pyodide_packages, { messageCallback: () => {} });
  await py.loadPackage(man.wheels.map((w) => base + 'wheels/' + w), { messageCallback: () => {} });
  const zip = await (await fetch(base + 'py/app.zip')).arrayBuffer();
  py.FS.mkdirTree('/app');
  py.unpackArchive(zip, 'zip', { extractDir: '/app' });
  py.FS.mkdirTree('/usr/share/fonts/truetype/nanum');
  py.FS.writeFile('/usr/share/fonts/truetype/nanum/NanumGothic.ttf',
    new Uint8Array(await (await fetch(base + 'fonts/NanumGothic.ttf')).arrayBuffer()));
  // 작은 모델 파일(토크나이저, 디코더 가중치, OCR 글자표)은 파이썬 쪽 가상 폴더에 둠
  for (const rel of m.pyFiles) {
    const dst = '/app/model/' + rel;
    py.FS.mkdirTree(dst.slice(0, dst.lastIndexOf('/')));
    py.FS.writeFile(dst, await cached(m.urls[rel], m.cacheName));
  }
  py.runPython("import sys; sys.path.insert(0, '/app')");
  api = py.pyimport('webapi');
  say('인식 모델 불러오는 중');
  const r = api.setup(py.toPy(m.placeholders));
  const res = r.toJs({ dict_converter: Object.fromEntries });
  r.destroy();
  return res;
}

// ---------------------------------------------------------------- 요청
const handlers = {
  init,
  async convert({ job, name, out, bytes, opts }) {
    const dir = '/input/' + job;
    py.FS.mkdirTree(dir);
    const path = dir + '/' + name;
    py.FS.writeFile(path, new Uint8Array(bytes));
    Atomics.store(cancel, 0, 0);
    const rep = JSON.parse(api.convert(job, path, out || name.replace(/\.pdf$/i, '') + '.hwpx', JSON.stringify(opts || {}),
      (d, t, msg) => self.postMessage({ type: 'progress', done: d, total: t, text: msg })));
    rep.hwpx = py.FS.readFile(rep.out);
    return rep;
  },
  useJob({ job }) { api.use_job(job); return null; },
  zip({ files }) { return py.FS.readFile(api.zip_outs(JSON.stringify(files))); },
  problems() { return JSON.parse(api.problems()); },
  problem({ k }) { return JSON.parse(api.problem(k)); },
  pageImage({ page }) { return api.page_image(page); },
  reread({ k, opts }) { return JSON.parse(api.reread(k, JSON.stringify(opts || {}))); },
  accept({ k }) { return JSON.parse(api.accept(k)); },
  drop({ k }) { api.drop(k); return null; },
  rebuild() {
    const r = JSON.parse(api.rebuild());
    r.hwpx = py.FS.readFile(r.out);
    return r;
  },
  readImage({ bytes }) { // 시험용
    py.FS.writeFile('/tmp/test.png', new Uint8Array(bytes));
    return JSON.parse(api.read_image('/tmp/test.png'));
  },
  runPython({ code }) { return String(py.runPython(code)); }, // 시험용
};

self.onmessage = async (ev) => {
  const { id, fn, args } = ev.data;
  try {
    const result = await handlers[fn](args || {});
    self.postMessage({ type: 'result', id, result });
  } catch (e) {
    self.postMessage({ type: 'result', id, error: String(e && e.message || e) });
  }
};
