// 화면 시험: 실제 페이지(index.html)에서 모델 받기 → PDF 변환 → .hwpx 내려받기 → 문제 확인(다시 읽기, 바꾸기, 영역 나누기) → 다시 만들기.
//   node web/test/e2e.mjs PDF 출력폴더 [쪽범위]
// Hugging Face 모델 주소는 serve.py 의 /local-models/ 로 돌려 받음 (MODEL_DIR).
import { createRequire } from 'module';
import fs from 'fs';
import path from 'path';
const { chromium } = createRequire(import.meta.url)('playwright');
const [pdf, outDir, pages] = process.argv.slice(2);
const BASE = process.env.BASE || 'http://127.0.0.1:8765/';
fs.mkdirSync(outDir, { recursive: true });
const browser = await chromium.launch({ args: (process.env.CHROME_ARGS || '').split(' ').filter(Boolean) });
const ctx = await browser.newContext({ acceptDownloads: true, viewport: { width: 1280, height: 900 }, deviceScaleFactor: 1 });
const page = await ctx.newPage();
const logs = [];
page.on('console', (m) => { logs.push(m.type() + ' ' + m.text()); if (process.env.VERBOSE || m.type() === 'error') console.log('[console]', m.type(), m.text().slice(0, 300)); });
page.on('pageerror', (e) => console.log('[pageerror]', e.message));
page.on('crash', () => console.log('[crash]'));
page.on('close', () => console.log('[close]'));
await ctx.route('https://huggingface.co/**', async (route) => {
  const url = route.request().url();
  const man = JSON.parse(fs.readFileSync(path.join(path.dirname(new URL(import.meta.url).pathname), '../dist/manifest.json')));
  const key = Object.entries(man.hf).find(([, u]) => u === url)?.[0];
  // 큰 파일은 fulfill 로 넘기면 Playwright 가 페이지를 닫아 버려서, 시험 서버로 돌려 보냄
  await route.fulfill({ status: 302, headers: { location: BASE + 'local-models/' + key, 'access-control-allow-origin': '*' } });
});
const t0 = Date.now();
const sec = () => ((Date.now() - t0) / 1000).toFixed(0) + 's';
await page.goto(BASE);
await page.waitForSelector('#btn-download:not([hidden]), #setup-msg.ok', { timeout: 60000 });
if (await page.isVisible('#btn-download')) {
  await page.screenshot({ path: path.join(outDir, '1_first.png') });
  await page.click('#btn-download');
}
await page.waitForSelector('#setup-msg.ok', { timeout: 300000 });
console.log(sec(), 'ready:', await page.textContent('#setup-msg'), '|', await page.textContent('#env'));
await page.setInputFiles('#file', pdf);
if (pages) await page.fill('#opt-pages', pages);
await page.screenshot({ path: path.join(outDir, '2_ready.png') });
const tc = Date.now();
await page.click('#btn-convert');
await page.waitForTimeout(8000);
await page.screenshot({ path: path.join(outDir, '3_converting.png') });
await page.waitForSelector('#result:not([hidden]), #cv-msg.err', { timeout: 3600000 });
const convSec = (Date.now() - tc) / 1000;
console.log(sec(), 'convert', convSec.toFixed(0) + 's:', await page.textContent('#cv-msg'));
console.log(await page.textContent('#report'));
const [dl] = await Promise.all([page.waitForEvent('download'), page.click('#btn-save')]);
await dl.saveAs(path.join(outDir, dl.suggestedFilename()));
console.log('saved', dl.suggestedFilename());
await page.screenshot({ path: path.join(outDir, '4_result.png'), fullPage: true });

// 문제 확인
await page.click('#btn-review');
await page.waitForSelector('#rv-main .cols', { timeout: 60000 });
await page.waitForTimeout(500);
await page.locator('#review').screenshot({ path: path.join(outDir, '5_review.png') });
const tr = Date.now();
await page.click('text=해상도 2배로 다시 읽기');
await page.waitForSelector('.pane.cand', { timeout: 600000 });
console.log(sec(), 'reread x2', ((Date.now() - tr) / 1000).toFixed(1) + 's');
await page.locator('#review').screenshot({ path: path.join(outDir, '6_candidate.png') });
await page.click('text=이 결과로 바꾸기');
await page.waitForSelector('#rv-msg.ok');
// 영역 나누기: 첫 자동 영역을 '그림'으로 정하고 다시 읽기
await page.click('text=수식·글·그림 영역 나누기…');
await page.waitForSelector('#dlg[open]');
await page.waitForTimeout(500);
const box = await page.locator('#dlg-canvas').boundingBox();
await page.mouse.move(box.x + box.width * 0.55, box.y + box.height * 0.3);
await page.mouse.down();
await page.mouse.move(box.x + box.width * 0.95, box.y + box.height * 0.7, { steps: 5 });
await page.mouse.up();
await page.locator('#dlg').screenshot({ path: path.join(outDir, '7_regions.png') });
await page.click('#dlg-ok');
await page.waitForSelector('.pane.cand', { timeout: 600000 });
await page.click('text=버리기');
// 영역 다시 잡기 창 열고 닫기
await page.click('text=문제 영역 다시 잡기…');
await page.waitForSelector('#dlg[open]');
await page.waitForTimeout(500);
await page.locator('#dlg').screenshot({ path: path.join(outDir, '8_box.png') });
await page.click('#dlg-cancel');
const [dl2] = await Promise.all([page.waitForEvent('download'), page.click('#btn-rebuild')]);
await dl2.saveAs(path.join(outDir, 'rebuilt_' + dl2.suggestedFilename()));
console.log(sec(), 'rebuilt:', await page.textContent('#rv-msg'));
const stats = await page.evaluate(() => null);
fs.writeFileSync(path.join(outDir, 'console.log'), logs.join('\n'));
fs.writeFileSync(path.join(outDir, 'timing.json'), JSON.stringify({ convert_sec: convSec }));
await browser.close();
