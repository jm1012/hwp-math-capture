// 화면: 모델 준비 → PDF 변환 → 결과 내려받기 → 문제 확인(원본과 결과 나란히, 다시 읽기, 영역 다시 잡기·나누기)
import { Engine } from './engine.js';

const $ = (id) => document.getElementById(id);
const eng = new Engine();
let jobs = [];        // PDF 마다 { id, file, state: wait|run|done|fail|stop, rep, hwpx: {name, bytes}, msg }
let nextJob = 1;
let reviewJob = null; // 문제 확인 중인 작업
let probs = [];       // 문제 목록
let cur = null;       // 지금 보는 문제 (problem 결과)
let cand = null;      // 다시 읽은 후보
let busy = false;
let rr = null;        // 다시 읽는 중: { k, t0, f, text, what, timer }

function bar(el, frac) { el.hidden = false; el.firstElementChild.style.width = `${Math.round(Math.max(0, Math.min(1, frac)) * 100)}%`; }
function mb(n) { return n < 1048576 ? Math.max(1, Math.round(n / 1024)) + 'KB' : (n / 1048576).toFixed(0) + 'MB'; }
function say(el, text, cls = '') { el.textContent = text; el.className = (el.className.replace(/\b(err|ok)\b/g, '').trim() + ' ' + cls).trim(); }
function download(name, bytes) {
  const url = URL.createObjectURL(new Blob([bytes], { type: /\.zip$/i.test(name) ? 'application/zip' : 'application/hwp+zip' }));
  const a = document.createElement('a');
  a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

// ---------------------------------------------------------------- 준비
async function boot() {
  const miss = Engine.check();
  if (miss.length) {
    say($('setup-msg'), `이 브라우저에서는 쓸 수 없습니다 (${miss.join(', ')} 없음). Chrome·Edge 최신판에서 열어 주세요. 처음 열 때는 페이지가 한 번 새로 고쳐질 수 있습니다.`, 'err');
    return;
  }
  const man = await eng.loadManifest();
  $('ver').textContent = man.version ? `v${man.version} 웹` : '웹';
  const saved = localStorageGet('ep');
  if (saved) $('opt-ep').value = saved;
  const miss2 = await eng.missingModels();
  if (miss2.length) {
    const total = miss2.reduce((s, f) => s + ((man.sizes || {})[f.key] || 0), 0);
    say($('setup-msg'), `처음 한 번 인식 모델${total ? `(${mb(total)})` : ''}을 받아 이 브라우저에 저장합니다. 받은 뒤에는 인터넷 없이도 변환할 수 있습니다.`);
    $('btn-download').hidden = false;
    $('btn-download').onclick = async () => {
      $('btn-download').disabled = true;
      try {
        await eng.download((got, tot, key) => {
          bar($('dl-bar'), tot ? got / tot : 0);
          say($('setup-msg'), `받는 중: ${key} (${mb(got)}${tot ? ' / ' + mb(tot) : ''})`);
        });
        $('btn-download').hidden = true;
        $('dl-bar').hidden = true;
        await startEngine();
      } catch (e) {
        say($('setup-msg'), `모델을 받지 못했습니다: ${e.message}`, 'err');
        $('btn-download').disabled = false;
      }
    };
  } else {
    await startEngine();
  }
}

function localStorageGet(k) { try { return localStorage.getItem('hwp-web-' + k); } catch (e) { return null; } }
function localStorageSet(k, v) { try { localStorage.setItem('hwp-web-' + k, v); } catch (e) { /* 무시 */ } }

async function startEngine() {
  say($('setup-msg'), '인식 엔진을 준비하는 중… (처음에는 1분쯤 걸릴 수 있음)');
  eng.onStatus = (t) => say($('setup-msg'), t + '…');
  try {
    const t0 = performance.now();
    const info = await eng.start({ ep: $('opt-ep').value });
    say($('setup-msg'), `준비 완료 (${((performance.now() - t0) / 1000).toFixed(0)}초)`, 'ok');
    $('env').textContent = `계산: ${info.webgpu ? 'WebGPU + CPU' : 'CPU (WASM)'}, CPU 스레드 ${info.threads}개` +
      (info.figures ? '' : ' · 그림 찾기 모델 없음');
    renderJobs();
  } catch (e) {
    say($('setup-msg'), `인식 엔진을 시작하지 못했습니다: ${e.message}`, 'err');
    console.error(e);
  }
}

// ---------------------------------------------------------------- 변환 (PDF 여러 개는 하나씩 차례로, 결과도 PDF 마다 따로)
const STATE = { wait: '대기', run: '변환 중', done: '완료', fail: '실패', stop: '멈춤' };

function addFiles(list) {
  const fs = [...(list || [])];
  const bad = fs.filter((f) => !/\.pdf$/i.test(f.name) && f.type !== 'application/pdf');
  for (const f of fs) if (!bad.includes(f)) jobs.push({ id: nextJob++, file: f, state: 'wait' });
  say($('cv-msg'), bad.length ? `PDF 가 아닌 파일 ${bad.length}개는 뺐습니다.` : '', bad.length ? 'err' : '');
  renderJobs();
}

function outName(job) {
  // 같은 이름 PDF 가 여럿이면 결과 이름이 겹치지 않게 (2), (3) …
  const base = job.file.name.replace(/\.pdf$/i, '');
  const same = jobs.filter((j) => j.file.name.replace(/\.pdf$/i, '') === base);
  const n = same.indexOf(job);
  return (n > 0 ? `${base} (${n + 1})` : base) + '.hwpx';
}

function renderJobs() {
  const waiting = jobs.filter((j) => j.state === 'wait').length;
  $('file-name').textContent = jobs.length ? `PDF ${jobs.length}개${waiting ? ` (변환할 것 ${waiting}개)` : ''} · 더 놓으면 뒤에 붙습니다` : '아직 고른 파일 없음 · 여러 개를 한꺼번에 놓아도 됩니다';
  const ul = $('jobs');
  ul.innerHTML = '';
  for (const j of jobs) {
    const li = document.createElement('li');
    li.className = 'job ' + j.state;
    const name = document.createElement('span');
    name.className = 'jname';
    name.textContent = `${j.file.name} (${mb(j.file.size)})`;
    const st = document.createElement('span');
    st.className = 'jstate';
    st.textContent = STATE[j.state] + (j.msg ? ' · ' + j.msg : '');
    li.append(name, st);
    const btns = document.createElement('span');
    btns.className = 'jbtns';
    const mk = (t, f, cls) => { const b = document.createElement('button'); b.textContent = t; b.onclick = f; if (cls) b.className = cls; btns.appendChild(b); return b; };
    if (j.state === 'done') {
      mk('.hwpx 내려받기', () => download(j.hwpx.name, j.hwpx.bytes), 'primary');
      mk('문제 확인', () => openReview(j)).disabled = busy;
    }
    if (j.state !== 'run' && !busy) mk('빼기', () => { jobs = jobs.filter((x) => x !== j); if (reviewJob === j) { $('review').hidden = true; reviewJob = null; } renderJobs(); });
    li.appendChild(btns);
    if (j.rep && j.state === 'done') {
      const rp = document.createElement('pre');
      rp.className = 'jrep small muted';
      rp.textContent = j.rep.text;
      li.appendChild(rp);
    }
    ul.appendChild(li);
  }
  const done = jobs.filter((j) => j.state === 'done');
  $('btn-zip').hidden = done.length < 2;
  $('btn-convert').disabled = !eng.ready || busy || !waiting;
  $('btn-convert').textContent = waiting > 1 ? `PDF ${waiting}개 한글 파일로 변환` : '한글 파일로 변환';
}

$('file').onchange = () => { addFiles($('file').files); $('file').value = ''; };
const drop = $('drop');
['dragenter', 'dragover'].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add('over'); }));
['dragleave', 'drop'].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove('over'); }));
// 창 아무 데나 놓아도 받음 (브라우저가 PDF 를 열어 버리지 않게)
window.addEventListener('dragover', (e) => e.preventDefault());
window.addEventListener('drop', (e) => { e.preventDefault(); if (e.dataTransfer?.files?.length) addFiles(e.dataTransfer.files); });

let stopAll = false;
$('btn-convert').onclick = async () => {
  if (busy) return;
  const todo = jobs.filter((j) => j.state === 'wait');
  if (!todo.length) return;
  busy = true;
  stopAll = false;
  $('btn-cancel').hidden = false;
  const opts = { pages: $('opt-pages').value.trim(), figures: $('opt-figures').checked, letters_unify: $('opt-letters').checked };
  const tAll = performance.now();
  for (const [n, j] of todo.entries()) {
    if (stopAll) break;
    j.state = 'run'; j.msg = '';
    renderJobs();
    const head = todo.length > 1 ? `(${n + 1}/${todo.length}) ${j.file.name} · ` : '';
    const t0 = performance.now();
    eng.onProgress = (p) => {
      bar($('cv-bar'), p.total ? p.done / p.total : 0);
      const el = (performance.now() - t0) / 1000;
      const left = p.done > 0 ? el * (p.total - p.done) / p.done : 0;
      say($('cv-msg'), `${head}${p.text} · ${el.toFixed(0)}초${left > 5 && p.done > p.total * 0.3 ? ` (남은 시간 약 ${Math.ceil(left / 60)}분)` : ''}`);
    };
    try {
      const bytes = await j.file.arrayBuffer();
      const rep = await eng.call('convert', { job: j.id, name: j.file.name, out: outName(j), bytes, opts }, [bytes]);
      j.rep = rep;
      j.hwpx = { name: outName(j), bytes: rep.hwpx };
      j.state = 'done';
      j.msg = `${((performance.now() - t0) / 1000).toFixed(0)}초`;
    } catch (e) {
      const m = String(e.message || e);
      if (/Cancelled/.test(m)) { j.state = 'stop'; j.msg = ''; stopAll = true; } else {
        j.state = 'fail';
        j.msg = m.split('\n').filter(Boolean).slice(-1)[0];
        console.error(m);
      }
    }
    renderJobs();
  }
  for (const j of jobs) if (j.state === 'stop') j.state = 'wait';
  busy = false;
  $('btn-cancel').hidden = true;
  bar($('cv-bar'), 1);
  const ok = todo.filter((j) => j.state === 'done').length;
  say($('cv-msg'), stopAll ? `멈췄습니다 (${ok}개 완료). 남은 PDF 는 [변환]을 다시 누르면 이어서 합니다.`
    : `${ok}/${todo.length}개 완료 (${((performance.now() - tAll) / 1000).toFixed(0)}초)`, stopAll ? '' : (ok === todo.length ? 'ok' : 'err'));
  renderJobs();
};
$('btn-cancel').onclick = () => { stopAll = true; eng.cancel(); say($('cv-msg'), '멈추는 중… (지금 문제를 마치면 멈춤)'); };
$('btn-zip').onclick = async () => {
  const done = jobs.filter((j) => j.state === 'done');
  const r = await eng.call('zip', { files: done.map((j) => ({ job: j.id, name: j.hwpx.name })) });
  download('한글변환_' + done.length + '개.zip', r);
};

// ---------------------------------------------------------------- 문제 확인
async function openReview(j) {
  if (busy) return;
  if (cand) { eng.call('drop', { k: cand.k }); cand = null; }
  await eng.call('useJob', { job: j.id });
  reviewJob = j;
  cur = null;
  $('rv-file').textContent = j.file.name;
  $('review').hidden = false;
  probs = await eng.call('problems');
  fillList();
  $('review').scrollIntoView({ behavior: 'smooth' });
  const first = probs.find((p) => p.flags.length) || probs[0];
  if (first) select(first.k);
}
$('only-flag').onchange = fillList;

function fillList() {
  const ul = $('rv-list');
  ul.innerHTML = '';
  const only = $('only-flag').checked;
  for (const p of probs) {
    if (only && !p.flags.length && !(cur && cur.k === p.k)) continue;
    const li = document.createElement('li');
    li.dataset.k = p.k;
    li.setAttribute('role', 'option');
    li.innerHTML = `${p.flags.length ? '<span class="flag">⚠</span> ' : ''}${p.label}${p.edited ? ' <span class="ed">✓ 고침</span>' : ''}`;
    if (cur && cur.k === p.k) li.classList.add('sel');
    li.onclick = () => select(p.k);
    ul.appendChild(li);
  }
  const nf = probs.filter((p) => p.flags.length).length;
  $('rv-summary').textContent = `문제 ${probs.length}개 중 확인할 문제 ${nf}개. ⚠ 는 결과 모양만 보고 찾은 것이라, 표시가 없어도 틀린 곳이 있을 수 있습니다.`;
  updateNav();
}

function visibleKs() { return [...$('rv-list').children].map((li) => Number(li.dataset.k)); }
function step(d) {
  if (!cur) return;
  const ks = visibleKs();
  const i = ks.indexOf(cur.k);
  const k = ks[i + d];
  if (k !== undefined) select(k);
}
function updateNav() {
  const ks = visibleKs();
  const i = cur ? ks.indexOf(cur.k) : -1;
  $('rv-prev').disabled = busy || i <= 0;
  $('rv-next').disabled = busy || i < 0 || i >= ks.length - 1;
  $('rv-pos').textContent = i >= 0 ? `${i + 1} / ${ks.length}` : '';
}
document.addEventListener('keydown', (e) => {
  if ($('review').hidden || $('dlg').open || /INPUT|SELECT|TEXTAREA/.test(e.target.tagName)) return;
  if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') { e.preventDefault(); step(-1); }
  if (e.key === 'ArrowRight' || e.key === 'ArrowDown') { e.preventDefault(); step(1); }
});
$('rv-prev').onclick = () => step(-1);
$('rv-next').onclick = () => step(1);

async function select(k) {
  if (busy) return;
  if (cand) { eng.call('drop', { k: cand.k }); cand = null; }
  try {
    cur = await eng.call('problem', { k });
  } catch (e) {
    say($('rv-msg'), `이 문제를 열지 못했습니다: ${e.message.split('\n').filter(Boolean).pop()}`, 'err');
    return;
  }
  fillList();
  renderMain();
  $('rv-list').querySelector('li.sel')?.scrollIntoView({ block: 'nearest' });
}

function mathHtml(latex, hwp) {
  const span = document.createElement('span');
  span.className = 'm' + (hwp == null ? ' bad' : '');
  span.title = hwp == null ? '한글 수식으로 못 바꿈: ' + latex : '한글 수식: ' + hwp;
  try { window.katex.render(latex, span, { throwOnError: false, strict: 'ignore' }); } catch (e) { span.textContent = latex; }
  return span;
}

function resultNode(result) {
  const div = document.createElement('div');
  div.className = 'res';
  if (result == null) { div.textContent = '(시험 안내 상자 — 그대로 넣음)'; return div; }
  if (cur && cur.kind === 'notice') { const n = document.createElement('p'); n.className = 'muted small'; n.textContent = '시험 안내 상자 (인식하지 않고 글 그대로 넣음)'; div.appendChild(n); }
  for (const para of result) {
    const p = document.createElement('p');
    for (const seg of para) {
      if (seg[0] === 'text') p.appendChild(document.createTextNode(seg[1]));
      else if (seg[0] === 'math') p.appendChild(mathHtml(seg[1], seg[2]));
      else if (seg[0] === 'image') { const im = new Image(); im.src = 'data:image/png;base64,' + seg[1]; im.alt = '그림'; p.appendChild(im); }
    }
    div.appendChild(p);
  }
  return div;
}

function reasonNode(flags, showNone) {
  const p = document.createElement('p');
  p.className = 'reason' + (flags.length ? '' : ' none');
  p.textContent = flags.length ? '확인할 점: ' + flags.join(', ') : (showNone ? '의심되는 곳 없음' : '');
  if (flags.some((f) => f.startsWith('읽지 않은 곳'))) {
    p.textContent += ' — 원본 그림의 빨간 상자. [수식·글·그림 영역 나누기]에서 그 상자를 눌러 종류를 정하면 다시 읽습니다.';
  }
  return p;
}

// 원본 문제 그림 + 읽지 않은 곳(빨간 상자)
function cropNode(png, regions) {
  const box = document.createElement('div');
  box.className = 'cropbox';
  const img = new Image();
  img.className = 'crop'; img.alt = '원본 문제 그림';
  img.onload = () => {
    for (const r of regions || []) {
      if (r.kind !== 'unread') continue;
      const d = document.createElement('div');
      d.className = 'unread';
      d.title = '읽지 않은 곳';
      const [x0, y0, x1, y1] = r.box, W = img.naturalWidth, H = img.naturalHeight;
      Object.assign(d.style, { left: `calc(${(x0 / W) * 100}% - 3px)`, top: `calc(${(y0 / H) * 100}% - 3px)`,
        width: `calc(${((x1 - x0) / W) * 100}% + 6px)`, height: `calc(${((y1 - y0) / H) * 100}% + 6px)` });
      box.appendChild(d);
    }
  };
  img.src = 'data:image/png;base64,' + png;
  box.appendChild(img);
  return box;
}

// 다시 읽는 중 표시
function rrNode() {
  const c = document.createElement('div');
  c.className = 'pane rr';
  c.setAttribute('role', 'status');
  c.innerHTML = '<div class="rr-head"><span class="spin" aria-hidden="true"></span><b>다시 읽는 중…</b> <span class="rr-text"></span></div><div class="bar"><div></div></div>';
  updateRR(c);
  return c;
}
function updateRR(el = document.querySelector('.pane.rr')) {
  if (!el || !rr) return;
  const sec = Math.floor((performance.now() - rr.t0) / 1000);
  el.querySelector('.rr-text').textContent = `${rr.what ? `(${rr.what}) ` : ''}${rr.text} · ${Math.round(rr.f * 100)}% · ${sec}초`;
  el.querySelector('.bar > div').style.width = `${Math.max(2, Math.round(rr.f * 100))}%`;
}

function renderMain() {
  updateNav();
  const m = $('rv-main');
  m.innerHTML = '';
  if (!cur) return;
  const cols = document.createElement('div');
  cols.className = 'cols';
  const a = document.createElement('div');
  a.className = 'pane';
  a.innerHTML = `<h3>원본 · ${cur.label}</h3>`;
  if (cur.crop) a.appendChild(cropNode(cur.crop, cur.regions));
  const b = document.createElement('div');
  b.className = 'pane';
  b.innerHTML = '<h3>인식 결과 <span class="hwpscript">(수식에 마우스를 올리면 한글 수식)</span></h3>';
  b.appendChild(reasonNode(cur.flags, false));
  b.appendChild(resultNode(cur.result));
  cols.append(a, b);
  m.appendChild(cols);
  if (cur.kind === 'notice') return;
  const tools = document.createElement('div');
  tools.className = 'tools';
  const mk = (t, f) => { const x = document.createElement('button'); x.textContent = t; x.onclick = f; x.disabled = busy; tools.appendChild(x); return x; };
  mk('해상도 2배로 다시 읽기', () => reread({ scale: 2 }, '해상도 2배로 다시 읽은 결과'));
  mk('문제 영역 다시 잡기…', pickBox);
  mk('수식·글·그림 영역 나누기…', editRegions);
  m.appendChild(tools);
  if (rr && rr.k === cur.k) m.appendChild(rrNode());
  if (cand && cand.k === cur.k) {
    const c = document.createElement('div');
    c.className = 'pane cand';
    c.innerHTML = `<h3>${cand.what}</h3>`;
    c.appendChild(reasonNode(cand.flags, true));
    c.appendChild(resultNode(cand.result));
    const row = document.createElement('div');
    row.className = 'tools';
    const ok = document.createElement('button'); ok.className = 'primary'; ok.textContent = '이 결과로 바꾸기';
    ok.onclick = accept;
    const no = document.createElement('button'); no.textContent = '버리기';
    no.onclick = () => { eng.call('drop', { k: cand.k }); cand = null; renderMain(); };
    row.append(ok, no);
    c.appendChild(row);
    m.appendChild(c);
  }
}

async function reread(opts, what) {
  if (!cur || busy) return;
  busy = true;
  const k = cur.k;
  rr = { k, t0: performance.now(), f: 0, text: '준비하는 중', what: opts.scale > 1 ? '해상도 2배' : opts.box ? '새 문제 영역' : opts.regions ? '정한 영역대로' : '' };
  eng.onProgress = (p) => { if (rr && p.what === 'reread') { rr.f = p.total ? p.done / p.total : 0; rr.text = p.text; updateRR(); } };
  rr.timer = setInterval(() => updateRR(), 250);
  if (cand) { eng.call('drop', { k: cand.k }); cand = null; }
  renderMain();
  document.querySelector('.pane.rr')?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  say($('rv-msg'), `${cur.label} 다시 읽는 중…`);
  try {
    const r = await eng.call('reread', { k, opts });
    r.what = what;
    if (cur && cur.k === k) { cand = r; say($('rv-msg'), '새 결과가 나왔습니다. 원본과 비교해 보세요.'); } else eng.call('drop', { k });
  } catch (e) {
    say($('rv-msg'), `다시 읽지 못했습니다: ${String(e.message).split('\n').filter(Boolean).slice(-1)[0]}`, 'err');
  } finally {
    clearInterval(rr.timer);
    rr = null;
    busy = false;
    renderMain();
  }
}

async function accept() {
  if (!cand) return;
  const k = cand.k;
  cur = await eng.call('accept', { k });
  cand = null;
  const p = probs.find((x) => x.k === k);
  if (p) { p.flags = cur.flags; p.edited = true; }
  fillList();
  renderMain();
  say($('rv-msg'), `${cur.label} 결과를 바꿨습니다. 다 고친 뒤 [고친 결과로 .hwpx 다시 만들기]를 누르세요.`, 'ok');
}

$('btn-rebuild').onclick = async () => {
  if (busy) return;
  try {
    const r = await eng.call('rebuild');
    reviewJob.hwpx = { name: reviewJob.hwpx.name, bytes: r.hwpx };
    download(reviewJob.hwpx.name, r.hwpx);
    say($('rv-msg'), `다시 만들었습니다 (문단 ${r.counts.paragraphs || 0}개, 수식 ${r.counts.equations || 0}개). 내려받은 파일을 한글에서 여세요.`, 'ok');
  } catch (e) {
    say($('rv-msg'), `만들지 못했습니다: ${e.message}`, 'err');
  }
};

// ---------------------------------------------------------------- 영역 고르기 창
const KIND = { math: ['수식', 'var(--math)'], text: ['글', 'var(--text)'], image: ['그림', 'var(--image)'] };
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v.slice(4, -1)).trim() || '#888';

function openDialog({ title, help, png, kinds, init, onOk, okText }) {
  const dlg = $('dlg'), cv = $('dlg-canvas'), ctx = cv.getContext('2d');
  $('dlg-title').textContent = title;
  $('dlg-help').textContent = help;
  $('dlg-ok').textContent = okText;
  const kb = $('dlg-kinds');
  kb.innerHTML = '';
  let mode = kinds ? 'image' : null;
  const st = init();
  if (kinds) {
    for (const [key, label] of [['math', '수식'], ['text', '글'], ['image', '그림'], ['erase', '지우기']]) {
      const b = document.createElement('button');
      b.textContent = label;
      b.style.color = key === 'erase' ? css('var(--warn)') : css(KIND[key][1]);
      b.onclick = () => { mode = key; [...kb.children].forEach((x) => x.classList.toggle('on', x === b)); };
      if (key === mode) b.classList.add('on');
      kb.appendChild(b);
    }
  }
  $('dlg-clear').hidden = !kinds;
  const img = new Image();
  img.onload = () => {
    const maxW = Math.min(window.innerWidth * 0.92, 1160), maxH = window.innerHeight * 0.7;
    const s = Math.min(2, maxW / img.width, kinds ? maxH / img.height : 99);
    cv.width = Math.round(img.width * s); cv.height = Math.round(img.height * s);
    st.s = s;
    draw();
  };
  img.src = 'data:image/png;base64,' + png;
  let drag = null;
  function draw(tmp) {
    ctx.clearRect(0, 0, cv.width, cv.height);
    ctx.drawImage(img, 0, 0, cv.width, cv.height);
    st.draw(ctx, st.s);
    if (tmp) {
      ctx.strokeStyle = kinds ? css(KIND[mode]?.[1] || 'var(--warn)') : '#d1242f';
      ctx.lineWidth = 2; ctx.setLineDash([]);
      ctx.strokeRect(tmp[0], tmp[1], tmp[2] - tmp[0], tmp[3] - tmp[1]);
    }
    $('dlg-info').textContent = st.info ? st.info() : '';
  }
  const pos = (e) => { const r = cv.getBoundingClientRect(); return [(e.clientX - r.left) * cv.width / r.width, (e.clientY - r.top) * cv.height / r.height]; };
  cv.onpointerdown = (e) => { drag = pos(e); cv.setPointerCapture(e.pointerId); };
  cv.onpointermove = (e) => { if (!drag || mode === 'erase') return; const p = pos(e); draw([Math.min(drag[0], p[0]), Math.min(drag[1], p[1]), Math.max(drag[0], p[0]), Math.max(drag[1], p[1])]); };
  cv.onpointerup = (e) => {
    if (!drag) return;
    const p = pos(e), d = drag; drag = null;
    st.up(d, p, mode);
    draw();
  };
  $('dlg-clear').onclick = () => { st.clear?.(); draw(); };
  $('dlg-cancel').onclick = () => dlg.close();
  $('dlg-ok').onclick = () => { const v = st.value(); if (v === undefined) return; dlg.close(); onOk(v); };
  dlg.showModal();
}

async function pickBox() {
  if (!cur || busy) return;
  const png = await eng.call('pageImage', { page: cur.page });
  const old = cur.box;
  openDialog({
    title: `문제 영역 다시 잡기 — ${cur.label}`,
    help: '쪽 그림에서 문제 영역을 마우스로 끌어서 잡으세요. 번호와 선지까지 넉넉하게 잡는 것이 좋습니다. 파란 상자가 지금 영역입니다.',
    png, okText: '이 영역으로 다시 읽기',
    init: () => ({
      box: null,
      draw(ctx, s) {
        ctx.setLineDash([6, 4]); ctx.lineWidth = 2; ctx.strokeStyle = '#1f6feb';
        ctx.strokeRect(old[0] * s, old[1] * s, (old[2] - old[0]) * s, (old[3] - old[1]) * s);
        if (this.box) { const b = this.box; ctx.setLineDash([]); ctx.strokeStyle = '#d1242f'; ctx.strokeRect(b[0] * s, b[1] * s, (b[2] - b[0]) * s, (b[3] - b[1]) * s); }
      },
      up(d, p) {
        const b = [Math.min(d[0], p[0]), Math.min(d[1], p[1]), Math.max(d[0], p[0]), Math.max(d[1], p[1])].map((v) => Math.round(v / this.s));
        if (b[2] - b[0] >= 10 && b[3] - b[1] >= 10) this.box = b;
      },
      info() { return this.box ? '새 영역을 잡았습니다.' : ''; },
      value() { return this.box || undefined; },
    }),
    onOk: (box) => reread({ box }, '새 영역으로 다시 읽은 결과'),
  });
}

function area(b) { return Math.max(0, b[2] - b[0]) * Math.max(0, b[3] - b[1]); }
function iou(a, b) {
  const i = Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0])) * Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]));
  return i / Math.max(1e-6, area(a) + area(b) - i);
}

function editRegions() {
  if (!cur || busy) return;
  const ai = (cur.regions || []).map((r) => ({ ...r }));
  openDialog({
    title: `수식·글·그림 영역 나누기 — ${cur.label}`,
    help: '종류를 고르고 드래그하면 새 영역. 점선(자동으로 나눈 영역)을 누르면 그 자리를 고른 종류로 정함. [지우기]를 고르고 실선을 누르면 지움. 정하지 않은 곳은 자동으로 읽습니다.',
    png: cur.crop, kinds: true, okText: '정한 영역대로 다시 읽기',
    init: () => ({
      user: (cur.user_regions || []).map((r) => ({ ...r })),
      draw(ctx, s) {
        ctx.lineWidth = 1; ctx.setLineDash([4, 3]);
        for (const r of ai) {
          if (this.user.some((u) => iou(r.box, u.box) > 0.5)) continue;
          if (r.kind === 'unread') { // 읽지 않은 곳: 빨간 상자 (누르면 고른 종류로 정함)
            ctx.save(); ctx.setLineDash([]); ctx.lineWidth = 2; ctx.strokeStyle = css('var(--warn)');
            ctx.strokeRect(r.box[0] * s - 3, r.box[1] * s - 3, (r.box[2] - r.box[0]) * s + 6, (r.box[3] - r.box[1]) * s + 6);
            ctx.restore();
            continue;
          }
          ctx.strokeStyle = css((KIND[r.kind] || ['', 'var(--muted)'])[1]);
          ctx.strokeRect(r.box[0] * s, r.box[1] * s, (r.box[2] - r.box[0]) * s, (r.box[3] - r.box[1]) * s);
        }
        ctx.setLineDash([]); ctx.lineWidth = 3; ctx.font = 'bold 13px sans-serif';
        for (const r of this.user) {
          const col = css(KIND[r.kind][1]);
          ctx.strokeStyle = col; ctx.fillStyle = col;
          ctx.strokeRect(r.box[0] * s, r.box[1] * s, (r.box[2] - r.box[0]) * s, (r.box[3] - r.box[1]) * s);
          ctx.fillText(KIND[r.kind][0], r.box[0] * s + 4, r.box[1] * s > 16 ? r.box[1] * s - 4 : r.box[3] * s + 14);
        }
      },
      up(d, p, mode) {
        const s = this.s, px = p[0] / s, py = p[1] / s;
        if (Math.abs(p[0] - d[0]) < 6 && Math.abs(p[1] - d[1]) < 6) { // 클릭
          const hit = (r) => r.box[0] <= px && px <= r.box[2] && r.box[1] <= py && py <= r.box[3];
          if (mode === 'erase') this.user = this.user.filter((r) => !hit(r));
          else {
            const c = [...this.user, ...ai].filter(hit).sort((a, b) => area(a.box) - area(b.box));
            if (c.length) { const b = [...c[0].box]; this.user = this.user.filter((r) => iou(r.box, b) <= 0.5).concat([{ box: b, kind: mode }]); }
          }
          return;
        }
        if (mode === 'erase') return;
        const b = [Math.min(d[0], p[0]), Math.min(d[1], p[1]), Math.max(d[0], p[0]), Math.max(d[1], p[1])].map((v) => Math.round(v / s * 10) / 10);
        this.user.push({ box: b, kind: mode });
      },
      clear() { this.user = []; },
      info() {
        if (!this.user.length) return '내가 정한 영역 없음 (정하지 않은 곳은 자동)';
        return '내가 정한 영역: ' + Object.keys(KIND).map((k) => [KIND[k][0], this.user.filter((r) => r.kind === k).length]).filter((x) => x[1]).map((x) => `${x[0]} ${x[1]}개`).join(', ');
      },
      value() { return this.user; },
    }),
    onOk: (regions) => reread({ regions }, '정한 영역대로 다시 읽은 결과'),
  });
}

// ---------------------------------------------------------------- 설정
$('opt-ep').onchange = () => { localStorageSet('ep', $('opt-ep').value); say($('setup-msg'), '계산 장치는 페이지를 새로 고치면 바뀝니다.'); };
$('btn-clear').onclick = async () => {
  if (!confirm('저장된 인식 모델을 지울까요? 다음에 쓸 때 다시 받아야 합니다.')) return;
  await Engine.clearModels();
  location.reload();
};

boot().catch((e) => {
  say($('setup-msg'), `준비하지 못했습니다: ${e.message}. Ctrl+F5 로 새로 고쳐 보세요.`, 'err');
  console.error(e);
});
