// 화면 시험: 실제 페이지(index.html)에서 모델 받기 → PDF 변환 → .hwpx 내려받기 → 문제 확인(다시 읽기, 바꾸기, 영역 나누기) → 다시 만들기.
//   node web/test/e2e.mjs PDF 출력폴더 [쪽범위]
// Hugging Face 모델 주소는 serve.py 의 /local-models/ 로 돌려 받음 (MODEL_DIR).
import { createRequire } from 'module';
import fs from 'fs';
import path from 'path';
const { chromium } = createRequire(import.meta.url)('playwright');
// PDF 는 쉼표로 여러 개 (각각 변환)
const [pdfArg, outDir, pages] = process.argv.slice(2);
const pdfs = pdfArg.split(',');
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
await page.setInputFiles('#file', pdfs);
if (pages) await page.fill('#opt-pages', pages);
await page.screenshot({ path: path.join(outDir, '2_ready.png') });
const tc = Date.now();
await page.click('#btn-convert');
await page.waitForTimeout(8000);
await page.screenshot({ path: path.join(outDir, '3_converting.png') });
await page.waitForFunction((n) => document.querySelectorAll('#jobs li.done, #jobs li.fail').length >= n, pdfs.length, { timeout: 3600000 });
const convSec = (Date.now() - tc) / 1000;
console.log(sec(), 'convert', convSec.toFixed(0) + 's:', await page.textContent('#cv-msg'));
console.log(await page.textContent('#jobs'));
for (const li of await page.$$('#jobs li.done')) {
  const [dl] = await Promise.all([page.waitForEvent('download'), (await li.$('text=.hwpx 내려받기')).click()]);
  await dl.saveAs(path.join(outDir, dl.suggestedFilename()));
  console.log('saved', dl.suggestedFilename());
}
if (pdfs.length > 1) {
  const [dz] = await Promise.all([page.waitForEvent('download'), page.click('#btn-zip')]);
  await dz.saveAs(path.join(outDir, dz.suggestedFilename()));
  console.log('saved zip', dz.suggestedFilename());
}
await page.screenshot({ path: path.join(outDir, '4_result.png'), fullPage: true });

// 문제 확인
const rows = await page.$$('#jobs li.done');
await (await rows[rows.length - 1].$('text=문제 확인')).click();
await page.waitForSelector('#rv-main .cols', { timeout: 60000 });
console.log('review of', await page.textContent('#rv-file'), await page.textContent('#rv-pos'));
const l0 = await page.textContent('#rv-main h3');
await page.click('#rv-next');
await page.waitForFunction((l) => document.querySelector('#rv-main h3')?.textContent !== l, l0);
console.log('next ->', await page.textContent('#rv-main h3'), await page.textContent('#rv-pos'));
await page.keyboard.press('ArrowLeft');
await page.waitForFunction((l) => document.querySelector('#rv-main h3')?.textContent === l, l0);
console.log('ArrowLeft ->', await page.textContent('#rv-main h3'));
await page.waitForTimeout(500);
await page.locator('#review').screenshot({ path: path.join(outDir, '5_review.png') });
// 읽지 않은 곳(빨간 상자)이 있는 문제가 있으면 그 문제로
const unreadRow = await page.$('#rv-list li:has(.flag)');
if (unreadRow) {
  const ks = await page.$$eval('#rv-list li', (ls) => ls.map((l) => l.dataset.k));
  for (const k of ks) {
    await page.click(`#rv-list li[data-k="${k}"]`);
    await page.waitForFunction((kk) => document.querySelector('#rv-list li.sel')?.dataset.k === kk, k);
    if (await page.$('#rv-main .cropbox .unread')) { console.log('unread boxes at', await page.textContent('#rv-main h3')); break; }
  }
  await page.waitForTimeout(300);
  await page.locator('#review').screenshot({ path: path.join(outDir, '5b_unread.png') });
}
const tr = Date.now();
await page.click('text=해상도 2배로 다시 읽기');
// 다시 읽는 중 표시: 진행 막대·하는 일·걸린 시간
await page.waitForSelector('.pane.rr', { timeout: 10000 });
await page.waitForTimeout(3000);
console.log('rereading:', await page.textContent('.pane.rr'));
await page.locator('#review').screenshot({ path: path.join(outDir, '5c_rereading.png') });
await page.waitForSelector('.pane.cand', { timeout: 600000 });
if (await page.$('.pane.rr')) throw new Error('다시 읽기가 끝났는데 진행 표시가 남아 있음');
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
