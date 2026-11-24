// 시험: 웹 엔진(브라우저 안 Pyodide + onnxruntime-web)으로 184장을 읽어 JSON 저장. native_run.py 와 같은 꼴.
//   node web/test/web_run.mjs 결과.json [이름 일부,...]     (serve.py 를 MODEL_DIR 와 함께 먼저 켬)
// EP=wasm|auto, THREADS=n, CHROME_ARGS="..." 로 바꿀 수 있음
import { createRequire } from 'module';
import fs from 'fs';
import path from 'path';
const { chromium } = createRequire(import.meta.url)('playwright');
const URL = process.env.URL || 'http://127.0.0.1:8765/test/harness.html';
const TESTSET = process.env.TESTSET || '/mnt/project-files/test-set';
let files = fs.readdirSync(TESTSET).filter((d) => /^20/.test(d)).sort()
  .flatMap((d) => fs.readdirSync(path.join(TESTSET, d)).filter((f) => f.endsWith('.png')).sort().map((f) => path.join(TESTSET, d, f)));
if (process.argv[3]) files = files.filter((f) => process.argv[3].split(',').some((k) => f.includes(k)));
const browser = await chromium.launch({ args: (process.env.CHROME_ARGS || '').split(' ').filter(Boolean) });
const page = await browser.newPage();
page.on('console', (m) => { if (process.env.VERBOSE || m.type() === 'error') console.log('[console]', m.type(), m.text().slice(0, 300)); });
page.on('pageerror', (e) => console.log('[pageerror]', e.message));
await page.goto(URL);
await page.waitForFunction(() => window.harnessReady);
const info = await page.evaluate(async ({ ep, threads }) => {
  const eng = window.eng = new window.Engine();
  await eng.loadManifest();
  for (const f of eng.files) if (f.url.includes('huggingface')) { f.url = location.origin + '/local-models/' + f.key; eng.urls[f.key] = f.url; }
  await eng.download();
  const t0 = performance.now();
  const r = await eng.start({ ep, numThreads: threads });
  return { ...r, start: (performance.now() - t0) / 1000 };
}, { ep: process.env.EP || 'wasm', threads: Number(process.env.THREADS) || 0 });
console.log('engine', JSON.stringify(info));
const res = {};
let tot = 0;
for (const [i, f] of files.entries()) {
  const b64 = fs.readFileSync(f).toString('base64');
  const r = await page.evaluate(async (b64) => {
    const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0)).buffer;
    const t0 = performance.now();
    try {
      const res = await window.eng.call('readImage', { bytes }, [bytes]);
      res.wall = (performance.now() - t0) / 1000;
      return res;
    } catch (e) { return { error: String(e.message || e) }; }
  }, b64);
  const name = path.basename(f, '.png');
  res[name] = r;
  tot += r.wall || 0;
  console.log(i + 1, name, r.error ? 'ERROR ' + r.error.slice(-300) : r.wall.toFixed(1));
}
res._info = { engine: info, total_sec: tot, stats: await page.evaluate(() => window.eng.stats()) };
fs.writeFileSync(process.argv[2], JSON.stringify(res));
console.log('total', tot.toFixed(0), 's');
await browser.close();
