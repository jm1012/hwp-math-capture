// 시험: 엔진을 띄워 그림 한 장 인식.  node web/test/smoke.mjs [그림...]
import { createRequire } from 'module';
const { chromium } = createRequire(import.meta.url)('playwright');
import fs from 'fs';
const URL = process.env.URL || 'http://127.0.0.1:8765/test/harness.html';
const browser = await chromium.launch({ args: (process.env.CHROME_ARGS || '').split(' ').filter(Boolean) });
const page = await browser.newPage();
page.on('console', (m) => { if (process.env.VERBOSE || m.type() === 'error') console.log('[console]', m.type(), m.text().slice(0, 500)); });
page.on('pageerror', (e) => console.log('[pageerror]', e.message));
await page.goto(URL);
await page.waitForFunction(() => window.harnessReady);
const info = await page.evaluate(async (ep) => {
  const E = window.Engine;
  const miss = E.check();
  if (miss.length) return { miss };
  const eng = window.eng = new E();
  eng.onStatus = (t) => console.log('status', t);
  await eng.loadManifest();
  for (const f of eng.files) { if (f.url.includes('huggingface')) { f.url = location.origin + '/local-models/' + f.key; eng.urls[f.key] = f.url; } }
  const t0 = performance.now();
  await eng.download();
  const t1 = performance.now();
  const r = await eng.start({ ep });
  return { ...r, dl: (t1 - t0) / 1000, start: (performance.now() - t1) / 1000 };
}, process.env.EP || 'wasm');
console.log('engine', JSON.stringify(info));
for (const f of process.argv.slice(2)) {
  const b64 = fs.readFileSync(f).toString('base64');
  const r = await page.evaluate(async (b64) => {
    const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0)).buffer;
    const t0 = performance.now();
    const res = await window.eng.call('readImage', { bytes }, [bytes]);
    res.wall = (performance.now() - t0) / 1000;
    return res;
  }, b64);
  console.log(f, r.wall.toFixed(1) + 's');
  console.log(r.md);
}
console.log(JSON.stringify(await page.evaluate(() => window.eng.stats())));
await browser.close();
