(function () {
  'use strict';

  /* ---------------- Hilfen ---------------- */
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const fmt = (v, d = 3) => {
    const r = Math.round(v * Math.pow(10, d)) / Math.pow(10, d);
    return (Object.is(r, -0) ? 0 : r).toLocaleString('de-AT', { maximumFractionDigits: d, useGrouping: false });
  };
  const shuffle = (a) => { const b = a.slice(); for (let i = b.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [b[i], b[j]] = [b[j], b[i]]; } return b; };
  const reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  let DATEN = { slug: 'seite', graphen: {}, themen: [], aufgaben: [], karten: [] };
  try { DATEN = JSON.parse($('#genutDaten').textContent); } catch (e) { /* ohne Daten weiter */ }

  /* ---------------- Speicher (pro Gerät, optional) ---------------- */
  const KEY = 'genut:' + DATEN.slug;
  let store = { gelesen: {}, geloest: {}, gewusst: {}, quiz: {}, theme: 'auto', letztesThema: null };
  try { const raw = localStorage.getItem(KEY); if (raw) store = Object.assign(store, JSON.parse(raw)); } catch (e) { /* nicht verfügbar */ }
  store.quiz = store.quiz || {};
  DATEN.quiz = DATEN.quiz || [];
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(store)); } catch (e) { /* ignorieren */ } };

  /* ---------------- Farbschema ---------------- */
  const THEMES = ['auto', 'light', 'dark'];
  const THEME_L = { auto: 'Auto', light: 'Hell', dark: 'Dunkel' };
  function applyTheme() {
    const t = store.theme || 'auto';
    if (t === 'auto') document.documentElement.removeAttribute('data-theme');
    else document.documentElement.setAttribute('data-theme', t);
    const l = $('#themeLabel'); if (l) l.textContent = THEME_L[t];
    const b = $('#themeBtn'); if (b) b.setAttribute('aria-label', 'Farbschema: ' + THEME_L[t]);
  }
  applyTheme();
  $('#themeBtn').addEventListener('click', () => {
    store.theme = THEMES[(THEMES.indexOf(store.theme || 'auto') + 1) % THEMES.length];
    save(); applyTheme(); redrawVisible();
  });

  /* ---------------- Fortschritt ---------------- */
  function renderProgress() {
    const nT = DATEN.themen.length, nA = DATEN.aufgaben.length, nK = DATEN.karten.length, nQ = DATEN.quiz.length;
    const g = DATEN.themen.filter(t => store.gelesen[t]).length;
    const a = DATEN.aufgaben.filter(t => store.geloest[t]).length;
    const k = DATEN.karten.filter(t => store.gewusst[t]).length;
    const q = DATEN.quiz.filter(t => store.quiz[t]).length;
    const total = nT + nA + nK + nQ;
    const pct = total ? Math.round((g + a + k + q) / total * 100) : 0;
    $('#progressText').textContent = pct + ' %';
    $('#progressBar').style.width = pct + '%';
    $('#progressSub').textContent = (g + a + k + q) === 0
      ? 'Noch nichts erledigt – fang mit dem ersten Thema an.'
      : `${g}/${nT} Themen gelesen · ${a}/${nA} Aufgaben gelöst · ${k}/${nK} Karten gewusst` + (nQ ? ` · ${q}/${nQ} Quizfragen richtig` : '');
    $$('[data-state]').forEach(el => { const ok = !!store.gelesen[el.dataset.state]; el.textContent = ok ? 'gelesen ✓' : 'offen'; el.classList.toggle('ok', ok); });
    $$('[data-gelesen]').forEach(b => { const ok = !!store.gelesen[b.dataset.gelesen]; b.setAttribute('aria-pressed', String(ok)); b.textContent = ok ? 'Gelesen ✓' : 'Als gelesen markieren'; });
    $$('[data-geloest]').forEach(b => {
      const ok = !!store.geloest[b.dataset.geloest];
      b.setAttribute('aria-pressed', String(ok)); b.textContent = ok ? 'Gelöst ✓' : 'Selbst gelöst';
      const t = b.closest('.task'); if (t) t.classList.toggle('geloest', ok);
    });
  }
  document.addEventListener('click', (e) => {
    const g = e.target.closest('[data-gelesen]');
    if (g) { const id = g.dataset.gelesen; store.gelesen[id] = !store.gelesen[id]; save(); renderProgress(); return; }
    const l = e.target.closest('[data-geloest]');
    if (l) { const id = l.dataset.geloest; store.geloest[id] = !store.geloest[id]; save(); renderProgress(); }
  });

  /* ---------------- Router ---------------- */
  const views = {};
  $$('.view').forEach(v => { views[v.dataset.view] = v; });
  const TAB_OF = (name) => name.startsWith('thema-') ? 'lernen' : name;
  let current = null;
  function route() {
    let h = decodeURIComponent(location.hash.slice(1)) || 'start';
    let param = null;
    if (h.startsWith('aufgaben/')) { param = h.slice(9); h = 'aufgaben'; }
    if (h === 'lernen') {
      const t = store.letztesThema && views['thema-' + store.letztesThema] ? store.letztesThema : DATEN.themen[0];
      h = t ? 'thema-' + t : 'start';
    }
    if (!views[h]) {
      // Anker auf ein Element (#el-…): zugehörige Ansicht öffnen
      const el = document.getElementById(h);
      const v = el && el.closest('.view');
      if (v) { show(v.dataset.view); el.scrollIntoView({ block: 'start' }); return; }
      h = 'start';
    }
    show(h);
    if (h === 'aufgaben') { $('#aufgThema').value = param || ''; filterAufgaben(); }
  }
  function show(name) {
    if (name !== current) {
      current = name;
      Object.entries(views).forEach(([k, v]) => { v.hidden = k !== name; });
      window.scrollTo(0, 0);
    }
    const tab = TAB_OF(name);
    $$('[data-tab]').forEach(a => { if (a.dataset.tab === tab) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
    if (name.startsWith('thema-')) { store.letztesThema = name.slice(6); save(); }
    if (name === 'karten') ensureCards();
    if (name === 'quiz') ensureQuiz();
    requestAnimationFrame(() => initPlotsIn(views[name]));
  }
  window.addEventListener('hashchange', route);

  /* ---------------- Schritt für Schritt aufdecken ---------------- */
  $$('.steps[data-reveal]').forEach(st => {
    const items = Array.from(st.children);
    let shown = 0;
    items.forEach(el => { el.hidden = true; });
    const ctl = document.createElement('div'); ctl.className = 'steps-ctl';
    const next = document.createElement('button'); next.type = 'button'; next.className = 'btn primary';
    const all = document.createElement('button'); all.type = 'button'; all.className = 'btn ghost'; all.textContent = 'Alle zeigen';
    const reset = document.createElement('button'); reset.type = 'button'; reset.className = 'btn ghost'; reset.textContent = 'Wieder verdecken';
    const count = document.createElement('span'); count.className = 'count';
    ctl.append(next, all, reset, count);
    st.after(ctl);
    const update = () => {
      const last = shown === items.length - 1;
      next.textContent = shown === 0 ? 'Ersten Schritt zeigen' : last ? 'Ergebnis zeigen' : 'Nächster Schritt';
      next.hidden = all.hidden = shown >= items.length;
      reset.hidden = shown === 0;
      count.textContent = Math.min(shown, items.length - 1) + ' / ' + (items.length - 1) + ' Schritte';
    };
    const reveal = (el) => { el.hidden = false; initPlotsIn(el); };
    next.addEventListener('click', () => {
      if (shown < items.length) {
        reveal(items[shown]); shown++; update();
        items[shown - 1].scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'nearest' });
      }
    });
    all.addEventListener('click', () => { items.forEach(reveal); shown = items.length; update(); });
    reset.addEventListener('click', () => { items.forEach(el => { el.hidden = true; }); shown = 0; update(); st.closest('details').scrollIntoView({ block: 'nearest' }); });
    update();
  });

  /* ---------------- Aufgaben-Filter ---------------- */
  let artFilter = '';
  function filterAufgaben() {
    const t = $('#aufgThema') ? $('#aufgThema').value : '';
    let n = 0;
    $$('#aufgListe .task').forEach(el => {
      const ok = (!t || el.dataset.thema === t) && (!artFilter || el.dataset.art === artFilter);
      el.hidden = !ok; if (ok) n++;
    });
    const leer = $('#aufgLeer'); if (leer) leer.hidden = n > 0 || !$$('#aufgListe .task').length;
  }
  if ($('#aufgThema')) $('#aufgThema').addEventListener('change', filterAufgaben);
  $$('.chip[data-art]').forEach(c => c.addEventListener('click', () => {
    artFilter = c.dataset.art;
    $$('.chip[data-art]').forEach(x => x.setAttribute('aria-pressed', String(x === c)));
    filterAufgaben();
  }));

  /* ---------------- Kopieren ---------------- */
  document.addEventListener('click', (e) => {
    const b = e.target.closest('[data-copy]');
    if (!b) return;
    const pre = b.closest('.code, .cmd').querySelector('pre');
    const done = (msg) => { b.textContent = msg; setTimeout(() => { b.textContent = 'Kopieren'; }, 1600); };
    const fallback = () => {
      try { const r = document.createRange(); r.selectNodeContents(pre); const s = window.getSelection(); s.removeAllRanges(); s.addRange(r); } catch (err) { /* ignorieren */ }
      done('Markiert');
    };
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(pre.textContent).then(() => done('Kopiert'), fallback);
      else fallback();
    } catch (err) { fallback(); }
  });

  /* ---------------- Drucken ---------------- */
  if ($('#printBtn')) $('#printBtn').addEventListener('click', () => window.print());

  /* ---------------- Karteikarten ---------------- */
  let deck = [], pos = 0, cardsReady = false;
  const bank = $$('#cardBank .fc');
  function buildDeck() {
    const t = $('#kartThema') ? $('#kartThema').value : '';
    deck = bank.filter(c => !t || c.dataset.thema === t);
    pos = 0;
    showCard();
  }
  function showCard() {
    const flash = $('#flash');
    if (!flash) return;
    flash.classList.remove('flipped');
    if (!deck.length) {
      $('#cardFront').innerHTML = '<p>Keine Karten für dieses Thema.</p>'; $('#cardBack').innerHTML = '';
      $('#cardTopic').textContent = ''; $('#cardPos').textContent = '0 / 0';
    } else {
      const c = deck[pos % deck.length];
      $('#cardFront').innerHTML = c.querySelector('.f').innerHTML;
      $('#cardBack').innerHTML = c.querySelector('.b').innerHTML;
      $('#cardTopic').textContent = c.dataset.themaTitel || '';
      $('#cardPos').textContent = (pos % deck.length + 1) + ' / ' + deck.length;
    }
    const known = deck.filter(c => store.gewusst[c.dataset.k]).length;
    $('#cardKnown').textContent = known + ' gewusst';
  }
  function ensureCards() {
    if (cardsReady || !$('#flash')) return;
    cardsReady = true;
    const flash = $('#flash');
    const flip = () => flash.classList.toggle('flipped');
    flash.addEventListener('click', flip);
    flash.addEventListener('keydown', (e) => { if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); flip(); } });
    $('#cardOk').addEventListener('click', () => {
      if (!deck.length) return;
      store.gewusst[deck[pos % deck.length].dataset.k] = true; save(); renderProgress();
      pos = (pos + 1) % deck.length; showCard();
    });
    $('#cardAgain').addEventListener('click', () => {
      if (!deck.length) return;
      const i = pos % deck.length;
      const [c] = deck.splice(i, 1);
      store.gewusst[c.dataset.k] = false; save(); renderProgress();
      deck.splice(Math.min(i + 3, deck.length), 0, c);
      if (pos >= deck.length) pos = 0;
      showCard();
    });
    $('#cardShuffle').addEventListener('click', () => { deck = shuffle(deck); pos = 0; showCard(); });
    if ($('#kartThema')) $('#kartThema').addEventListener('change', buildDeck);
    buildDeck();
  }

  /* ---------------- Graphen ---------------- */
  function colors() {
    const s = getComputedStyle(document.documentElement);
    const g = (n) => s.getPropertyValue(n).trim();
    return { grid: g('--plot-grid'), axis: g('--plot-axis'), muted: g('--muted'), surface: g('--surface'),
      f: [g('--plot-1'), g('--plot-2'), g('--plot-3'), g('--plot-4')], sans: g('--sans') || 'sans-serif' };
  }
  function alpha(color, a) {
    const m = /^#([0-9a-f]{6})$/i.exec(color);
    if (!m) return color;
    const n = parseInt(m[1], 16);
    return 'rgba(' + (n >> 16 & 255) + ',' + (n >> 8 & 255) + ',' + (n & 255) + ',' + a + ')';
  }
  function niceStep(range, target) {
    const raw = range / target;
    const p = Math.pow(10, Math.floor(Math.log10(raw)));
    const m = raw / p;
    return (m < 1.5 ? 1 : m < 3.5 ? 2 : m < 7.5 ? 5 : 10) * p;
  }
  const plots = new Map();
  // Fester y-Bereich über alle Reglerstellungen (min/start/max je Parameter). Würde die Achse bei jedem
  // Neuzeichnen an die aktuellen Werte angepasst, zoomte sie beim Schieben mit und die Kurve bliebe
  // optisch an derselben Stelle stehen – der Regler sähe wirkungslos aus.
  function yBereich(g, fns) {
    const [gy0, gy1] = g.y;
    if (gy0 !== null && gy1 !== null) return [gy0, gy1];
    const stufen = g.p.map(p => Array.from(new Set([p.min, p.start, p.max])));
    let kombis = [[]];
    if (stufen.reduce((n, s) => n * s.length, 1) <= 243) {
      stufen.forEach(s => { kombis = kombis.flatMap(k => s.map(v => k.concat(v))); });
    } else {
      const start = g.p.map(p => p.start);
      kombis = [start];
      g.p.forEach((p, i) => [p.min, p.max].forEach(v => { const k = start.slice(); k[i] = v; kombis.push(k); }));
    }
    const [x0, x1] = g.x, N = 200;
    let lo = Infinity, hi = -Infinity;
    kombis.forEach(args => fns.forEach(fn => {
      const ys = [];
      for (let i = 0; i <= N; i++) {
        let y; try { y = fn(x0 + (x1 - x0) * i / N, ...args); } catch (e) { y = NaN; }
        if (typeof y === 'number' && isFinite(y)) ys.push(y);
      }
      if (!ys.length) return;
      ys.sort((a, b) => a - b);  // 2 %/98 %-Quantil je Kurve: Polstellen sprengen die Achse nicht
      lo = Math.min(lo, ys[Math.floor(ys.length * 0.02)]);
      hi = Math.max(hi, ys[Math.ceil(ys.length * 0.98) - 1]);
    }));
    if (!isFinite(lo)) { lo = -1; hi = 1; }
    if (lo > 0) lo = 0; if (hi < 0) hi = 0;  // x-Achse bleibt sichtbar
    let a = gy0 !== null ? gy0 : lo, b = gy1 !== null ? gy1 : hi;
    if (b - a < 1e-9) { if (gy0 === null) a -= 1; if (gy1 === null) b += 1; }
    const pad = (b - a) * 0.1;
    return [gy0 !== null ? gy0 : a - pad, gy1 !== null ? gy1 : b + pad];
  }
  function makePlot(el) {
    const g = DATEN.graphen[el.dataset.graph];
    if (!g) return null;
    const names = g.p.map(p => p.name);
    const fns = g.f.map(f => {
      try { return new Function('x', ...names, '"use strict"; return (' + f.js + ');'); } catch (e) { return () => NaN; }
    });
    const vals = {};
    g.p.forEach(p => { vals[p.name] = p.start; });
    const plot = { el, g, fns, vals, canvas: $('canvas', el), yr: yBereich(g, fns) };
    $$('input[type=range]', el).forEach(inp => {
      inp.addEventListener('input', () => {
        vals[inp.dataset.p] = parseFloat(inp.value);
        const out = inp.closest('.slider').querySelector('output');
        if (out) out.textContent = fmt(vals[inp.dataset.p], 3);
        draw(plot);
      });
      const out = inp.closest('.slider').querySelector('output');
      if (out) out.textContent = fmt(parseFloat(inp.value), 3);
    });
    return plot;
  }
  function draw(plot) {
    const { canvas: cv, g, fns, vals, yr } = plot;
    if (!cv || !cv.offsetParent) return;
    const w = Math.max(240, Math.round(cv.parentElement.clientWidth));
    const h = Math.round(w * (w < 520 ? 0.72 : 0.62));
    const dpr = Math.min(window.devicePixelRatio || 1, 2.5);
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
    cv.style.height = h + 'px';
    const ctx = cv.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const C = colors();
    const args = g.p.map(p => vals[p.name]);
    const [x0, x1] = g.x;
    const N = Math.min(800, Math.max(240, w * 1.5));
    const samples = fns.map(fn => {
      const pts = [];
      for (let i = 0; i <= N; i++) {
        const x = x0 + (x1 - x0) * i / N;
        let y; try { y = fn(x, ...args); } catch (e) { y = NaN; }
        pts.push([x, (typeof y === 'number' && isFinite(y)) ? y : NaN]);
      }
      return pts;
    });
    const [y0, y1] = yr;
    const P = { l: 40, r: 12, t: 12, b: 26 };
    const iw = w - P.l - P.r, ih = h - P.t - P.b;
    const X = (x) => P.l + (x - x0) / (x1 - x0) * iw;
    const Y = (y) => P.t + (1 - (y - y0) / (y1 - y0)) * ih;
    // Gitter + Achsen
    ctx.font = '11px ' + C.sans; ctx.lineWidth = 1;
    const sx = niceStep(x1 - x0, iw < 330 ? 5 : 8), sy = niceStep(y1 - y0, ih < 160 ? 4 : 6);
    ctx.strokeStyle = C.grid; ctx.beginPath();
    for (let v = Math.ceil(x0 / sx) * sx; v <= x1 + sx * 1e-6; v += sx) { const px = Math.round(X(v)) + 0.5; ctx.moveTo(px, P.t); ctx.lineTo(px, h - P.b); }
    for (let v = Math.ceil(y0 / sy) * sy; v <= y1 + sy * 1e-6; v += sy) { const py = Math.round(Y(v)) + 0.5; ctx.moveTo(P.l, py); ctx.lineTo(w - P.r, py); }
    ctx.stroke();
    const ax = (x0 <= 0 && x1 >= 0) ? Math.round(X(0)) + 0.5 : P.l + 0.5;
    const ay = (y0 <= 0 && y1 >= 0) ? Math.round(Y(0)) + 0.5 : h - P.b + 0.5;
    ctx.strokeStyle = C.axis; ctx.beginPath(); ctx.moveTo(P.l, ay); ctx.lineTo(w - P.r, ay); ctx.moveTo(ax, P.t); ctx.lineTo(ax, h - P.b); ctx.stroke();
    ctx.fillStyle = C.muted; ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    for (let v = Math.ceil(x0 / sx) * sx; v <= x1 + sx * 1e-6; v += sx) { if (Math.abs(v) < sx * 1e-6 && ax > P.l + 1) continue; ctx.fillText(fmt(v), X(v), h - P.b + 6); }
    ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
    for (let v = Math.ceil(y0 / sy) * sy; v <= y1 + sy * 1e-6; v += sy) ctx.fillText(fmt(v), P.l - 6, Y(v));
    ctx.save(); ctx.beginPath(); ctx.rect(P.l, P.t, iw, ih); ctx.clip();
    // Fläche
    if (g.fl && samples[g.fl.funktion]) {
      const col = C.f[g.fl.funktion % 4];
      ctx.fillStyle = alpha(col, 0.18); ctx.beginPath(); ctx.moveTo(X(g.fl.von), Y(0));
      samples[g.fl.funktion].forEach(([x, y]) => { if (x >= g.fl.von && x <= g.fl.bis && isFinite(y)) ctx.lineTo(X(x), Y(y)); });
      ctx.lineTo(X(g.fl.bis), Y(0)); ctx.closePath(); ctx.fill();
    }
    // Kurven, bei Unstetigkeit Linie unterbrechen
    const jump = (y1 - y0) * 10;
    samples.forEach((pts, i) => {
      ctx.strokeStyle = C.f[i % 4]; ctx.lineWidth = 2.5; ctx.lineJoin = 'round'; ctx.lineCap = 'round';
      ctx.beginPath(); let pen = false, prev = null;
      pts.forEach(([x, y]) => {
        if (!isFinite(y) || (prev !== null && Math.abs(y - prev) > jump)) { pen = false; prev = isFinite(y) ? y : null; if (!isFinite(y)) return; }
        if (!pen) { ctx.moveTo(X(x), Y(y)); pen = true; } else ctx.lineTo(X(x), Y(y));
        prev = y;
      });
      ctx.stroke();
    });
    ctx.restore();
  }
  function initPlotsIn(root) {
    if (!root) return;
    $$('.plot[data-graph]', root).forEach(el => {
      let p = plots.get(el);
      if (!p) { p = makePlot(el); if (!p) return; plots.set(el, p); }
      draw(p);
    });
  }
  function redrawVisible() { plots.forEach(p => draw(p)); }
  let rt = null;
  window.addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(redrawVisible, 120); });
  try { window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', redrawVisible); } catch (e) { /* alte Browser */ }
  document.addEventListener('toggle', (e) => { if (e.target.matches && e.target.matches('details')) initPlotsIn(e.target); }, true);

  /* ---------------- Quiz ---------------- */
  const quizBank = $$('#quizBank .qz');
  let qQueue = [], qIdx = 0, qErste = {}, qRunde = [], quizReady = false;
  function quizStart(nurFalsche) {
    const t = $('#quizThema') ? $('#quizThema').value : '';
    let fragen = quizBank.filter(q => !t || q.dataset.thema === t);
    if (nurFalsche) fragen = fragen.filter(q => qErste[q.dataset.q] === false);
    qErste = {}; qRunde = fragen; qQueue = shuffle(fragen); qIdx = 0;
    quizZeigen();
  }
  function quizStand() {
    const n = qRunde.length, beantwortet = Object.keys(qErste).length;
    const richtig = Object.values(qErste).filter(Boolean).length;
    $('#quizStand').textContent = n ? `${Math.min(beantwortet, n)} / ${n} · ${richtig} richtig` : '';
    $('#quizBar').style.width = (n ? Math.round(beantwortet / n * 100) : 0) + '%';
  }
  function quizZeigen() {
    const box = $('#quizKarte');
    quizStand();
    if (!qQueue.length && !qRunde.length) { box.innerHTML = '<p class="leer">Keine Fragen für dieses Thema.</p>'; return; }
    if (qIdx >= qQueue.length) {
      const n = qRunde.length, r = Object.values(qErste).filter(Boolean).length, falsch = n - r;
      box.innerHTML = `<div class="qz-ende"><div class="eyebrow">Geschafft</div><div class="qz-score">${r} / ${n}</div>
        <p>${r === n ? 'Alles beim ersten Versuch richtig – stark!' : 'beim ersten Versuch richtig'}</p>
        <div class="btn-row"><button type="button" class="btn primary" id="qzNeu">Nochmal alle</button>
        ${falsch ? `<button type="button" class="btn" id="qzFalsch">Nur die ${falsch} falschen</button>` : ''}</div></div>`;
      $('#qzNeu').addEventListener('click', () => quizStart(false));
      if ($('#qzFalsch')) $('#qzFalsch').addEventListener('click', () => quizStart(true));
      return;
    }
    const q = qQueue[qIdx], id = q.dataset.q, mc = q.dataset.art === 'mc';
    const wiederholt = id in qErste;
    let opts;
    if (mc) {
      const o = $$('.qo', q).map((el, i) => ({ html: el.innerHTML, i }));
      opts = shuffle(o);
    } else {
      opts = [{ html: '<p>Wahr</p>', i: 'true' }, { html: '<p>Falsch</p>', i: 'false' }];
    }
    box.innerHTML = `<div class="qz-top"><span>${q.dataset.themaTitel || ''}</span><span>Frage ${Math.min(qIdx + 1, qQueue.length)} von ${qQueue.length}${wiederholt ? ' · Wiederholung' : ''}</span></div>
      <div class="qz-frage prose">${$('.qf', q).innerHTML}</div>
      <div class="qz-opts${mc ? '' : ' qz-wf'}">${opts.map((o, k) => `<button type="button" class="qz-opt" data-i="${o.i}">${mc ? `<span class="qz-l">${'ABCD'[k] || k + 1}</span>` : ''}<div class="prose">${o.html}</div></button>`).join('')}</div>
      <div class="qz-fb" hidden></div>`;
    $$('.qz-opt', box).forEach(b => b.addEventListener('click', () => {
      const richtigI = mc ? q.dataset.richtig : q.dataset.wahr;
      const ok = String(b.dataset.i) === String(richtigI);
      $$('.qz-opt', box).forEach(x => { x.disabled = true; if (String(x.dataset.i) === String(richtigI)) x.classList.add('richtig'); });
      if (!ok) b.classList.add('falsch');
      if (!(id in qErste)) qErste[id] = ok;
      if (ok) { store.quiz[id] = true; save(); renderProgress(); }
      else qQueue.push(q);  // falsch → am Ende nochmal
      const fb = $('.qz-fb', box);
      fb.hidden = false; fb.className = 'qz-fb ' + (ok ? 'ok' : 'nok');
      fb.innerHTML = `<b>${ok ? 'Richtig!' : 'Leider falsch.'}</b><div class="prose">${$('.qe', q).innerHTML}</div>
        <div class="btn-row" style="justify-content:flex-end"><button type="button" class="btn primary" id="qzWeiter">${qIdx + 1 < qQueue.length ? 'Weiter' : 'Auswertung'}</button></div>`;
      quizStand();
      const w = $('#qzWeiter'); w.addEventListener('click', () => { qIdx++; quizZeigen(); }); w.focus({ preventScroll: true });
    }));
  }
  function ensureQuiz() {
    if (quizReady || !$('#quizKarte')) return;
    quizReady = true;
    if ($('#quizThema')) $('#quizThema').addEventListener('change', () => quizStart(false));
    quizStart(false);
  }

  /* ---------------- Lückentext ---------------- */
  const norm = (t) => String(t).replace(/[’‘`´]/g, "'").replace(/[“”„]/g, '"').replace(/\s+/g, ' ').trim().toLowerCase();
  $$('[data-lueckentext]').forEach(box => {
    const felder = $$('input.lk', box);
    const stand = $('.lt-stand', box);
    const loes = (f) => { try { return JSON.parse(f.dataset.loesung); } catch (e) { return []; } };
    $('[data-lt-pruefen]', box).addEventListener('click', () => {
      let r = 0;
      felder.forEach(f => {
        const ok = loes(f).some(l => norm(l) === norm(f.value));
        f.classList.toggle('richtig', ok); f.classList.toggle('falsch', !ok && f.value.trim() !== '');
        if (ok) r++;
      });
      stand.textContent = `${r} von ${felder.length} richtig`;
    });
    $('[data-lt-zeigen]', box).addEventListener('click', () => {
      felder.forEach(f => {
        if (!loes(f).some(l => norm(l) === norm(f.value))) { f.value = loes(f)[0] || ''; f.classList.remove('falsch'); f.classList.add('richtig'); }
      });
      stand.textContent = 'Lösungen eingetragen';
    });
    $('[data-lt-reset]', box).addEventListener('click', () => {
      felder.forEach(f => { f.value = ''; f.classList.remove('richtig', 'falsch'); });
      stand.textContent = '';
    });
    felder.forEach((f, i) => f.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); (felder[i + 1] || $('[data-lt-pruefen]', box)).focus(); }
    }));
  });

  /* ---------------- SQL (sql.js, offline) ---------------- */
  let sqlInit = null;
  function sqlLaden() {
    if (sqlInit) return sqlInit;
    sqlInit = new Promise((ok, fehler) => {
      try {
        if (typeof window.initSqlJs !== 'function' || !window.GENUT_SQL_WASM) throw new Error('SQL-Laufzeit fehlt in dieser Datei');
        const bin = Uint8Array.from(atob(window.GENUT_SQL_WASM), c => c.charCodeAt(0));
        window.initSqlJs({ wasmBinary: bin }).then(ok, fehler);
      } catch (e) { fehler(e); }
    });
    return sqlInit;
  }
  const esc = (t) => String(t).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  $$('[data-sql]').forEach(box => {
    const ed = $('.sql-ed', box), out = $('[data-sql-out]', box), status = $('.sql-status', box);
    const schema = $('.sql-schema-code', box).textContent;
    const original = ed.value;
    const run = () => {
      status.textContent = 'läuft …';
      sqlLaden().then(SQL => {
        const db = new SQL.Database();
        try {
          db.run(schema);
          const res = db.exec(ed.value);
          if (!res.length) { out.innerHTML = '<p class="sql-status">Anweisung ausgeführt (kein Ergebnis).</p>'; }
          else {
            const r = res[res.length - 1];
            out.innerHTML = `<div class="tbl-wrap" tabindex="0"><table><thead><tr>${r.columns.map(c => `<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>` +
              r.values.slice(0, 200).map(z => `<tr>${z.map(v => `<td>${v === null ? 'NULL' : esc(v)}</td>`).join('')}</tr>`).join('') + '</tbody></table></div>';
          }
          status.textContent = res.length ? `${res[res.length - 1].values.length} Zeile(n)` : 'fertig';
        } catch (e) {
          out.innerHTML = `<div class="sql-err">${esc(e.message)}</div>`; status.textContent = 'Fehler';
        } finally { db.close(); }
      }, e => { status.textContent = 'SQL nicht verfügbar: ' + e.message; });
    };
    $('[data-sql-run]', box).addEventListener('click', run);
    ed.addEventListener('keydown', (e) => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); run(); } });
    $('[data-sql-reset]', box).addEventListener('click', () => { ed.value = original; status.textContent = ''; });
    const l = $('[data-sql-loesung]', box);
    if (l) l.addEventListener('click', () => { ed.value = ed.dataset.loesung || ''; run(); });
  });

  /* ---------------- Subnetz-Rechner (IPv4 + IPv6) ---------------- */
  function v4(text) {
    const m = /^\s*(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\s*\/\s*(\d{1,2})\s*$/.exec(text);
    if (!m) return null;
    const o = m.slice(1, 5).map(Number), p = Number(m[5]);
    if (o.some(x => x > 255) || p > 32) return null;
    return { ip: ((o[0] << 24) | (o[1] << 16) | (o[2] << 8) | o[3]) >>> 0, p };
  }
  const v4s = (n) => [n >>> 24, (n >>> 16) & 255, (n >>> 8) & 255, n & 255].join('.');
  const v4b = (n) => [n >>> 24, (n >>> 16) & 255, (n >>> 8) & 255, n & 255].map(x => x.toString(2).padStart(8, '0')).join('.');
  function v6(text) {
    const m = /^\s*([0-9a-fA-F:.]+)\s*\/\s*(\d{1,3})\s*$/.exec(text);
    if (!m || typeof BigInt !== 'function') return null;
    const p = Number(m[2]); if (p > 128) return null;
    let teile = m[1].split('::');
    if (teile.length > 2) return null;
    const links = teile[0] ? teile[0].split(':') : [], rechts = teile.length > 1 && teile[1] ? teile[1].split(':') : [];
    const fehlt = 8 - links.length - rechts.length;
    if ((teile.length === 1 && fehlt !== 0) || fehlt < 0) return null;
    const gruppen = links.concat(Array(teile.length > 1 ? fehlt : 0).fill('0'), rechts);
    if (gruppen.length !== 8 || gruppen.some(g => !/^[0-9a-fA-F]{1,4}$/.test(g))) return null;
    let n = 0n; gruppen.forEach(g => { n = (n << 16n) | BigInt(parseInt(g, 16)); });
    return { ip: n, p };
  }
  function v6s(n) {
    const g = []; for (let i = 7; i >= 0; i--) g.push(Number((n >> BigInt(i * 16)) & 0xffffn).toString(16));
    let best = [-1, 0], cur = [-1, 0];
    g.forEach((x, i) => { if (x === '0') { if (cur[0] < 0) cur = [i, 0]; cur[1]++; if (cur[1] > best[1]) best = cur.slice(); } else cur = [-1, 0]; });
    if (best[1] < 2) return g.join(':');
    return (g.slice(0, best[0]).join(':') + '::' + g.slice(best[0] + best[1]).join(':')).replace(/^:::/, '::');
  }
  $$('[data-subnetz]').forEach(box => {
    const inp = $('.sn-in', box), tb = $('.sn-out tbody', box), err = $('.sn-fehler', box);
    const zeile = (k, v, bin) => `<tr><th>${k}</th><td>${v}${bin ? `<span class="bin">${bin}</span>` : ''}</td></tr>`;
    const rechnen = () => {
      const a = v4(inp.value);
      if (a) {
        const maske = a.p === 0 ? 0 : (0xffffffff << (32 - a.p)) >>> 0;
        const netz = (a.ip & maske) >>> 0, bc = (netz | (~maske >>> 0)) >>> 0;
        const anz = Math.pow(2, 32 - a.p), hosts = a.p <= 30 ? anz - 2 : anz;
        const erster = a.p <= 30 ? netz + 1 : netz, letzter = a.p <= 30 ? bc - 1 : bc;
        err.textContent = '';
        tb.innerHTML = zeile('Netzadresse', v4s(netz), v4b(netz)) + zeile('Subnetzmaske', `${v4s(maske)} (/${a.p})`, v4b(maske)) +
          zeile('Broadcast', v4s(bc), v4b(bc)) + zeile('Erster Host', v4s(erster)) + zeile('Letzter Host', v4s(letzter)) +
          zeile('Nutzbare Hosts', hosts.toLocaleString('de-AT')) + zeile('Wildcard', v4s(~maske >>> 0));
        return;
      }
      const b = v6(inp.value);
      if (b) {
        const alle = (1n << 128n) - 1n, maske = b.p === 0 ? 0n : (alle << BigInt(128 - b.p)) & alle;
        const netz = b.ip & maske, letzte = netz | (~maske & alle);
        err.textContent = '';
        tb.innerHTML = zeile('Netzadresse', `${v6s(netz)}/${b.p}`) + zeile('Präfix', `/${b.p} (${128 - b.p} Bit Interface-Teil)`) +
          zeile('Erste Adresse', v6s(b.p < 128 ? netz + 1n : netz)) + zeile('Letzte Adresse', v6s(letzte)) +
          zeile('Adressen', b.p >= 64 ? (2n ** BigInt(128 - b.p)).toLocaleString('de-AT') : `2^${128 - b.p}`);
        return;
      }
      tb.innerHTML = ''; err.textContent = 'Bitte z. B. 192.168.1.10/24 oder 2001:db8::1/64 eingeben.';
    };
    inp.addEventListener('input', rechnen);
    rechnen();
  });

  /* ---------------- Code: Zeilen zu Erklärungen hervorheben ---------------- */
  $$('[data-zeilen-code]').forEach(code => {
    const liste = code.nextElementSibling;
    if (!liste || !liste.classList.contains('code-erkl')) return;
    const zeilen = $$('.cl', code);
    const markieren = (li, an) => {
      const [v, b] = String(li.dataset.zeilen).split(/[-–]/).map(x => parseInt(x, 10));
      zeilen.forEach(z => { const n = +z.dataset.l; if (n >= v && n <= (b || v)) z.classList.toggle('hl', an); });
    };
    $$('li', liste).forEach(li => {
      ['mouseenter', 'focus'].forEach(ev => li.addEventListener(ev, () => markieren(li, true)));
      ['mouseleave', 'blur'].forEach(ev => li.addEventListener(ev, () => markieren(li, false)));
      li.addEventListener('click', () => { const an = !li.classList.contains('aktiv'); li.classList.toggle('aktiv', an); markieren(li, an); });
    });
  });

  /* ---------------- Vorschau im Tool (nur mit ?vorschau=1 aktiv) ---------------- */
  if (/[?&]vorschau=1/.test(location.search)) {
    window.addEventListener('message', (e) => {
      const id = e.data && e.data.genutZeige;
      if (!id) return;
      const el = document.getElementById('el-' + id) || document.getElementById('v-thema-' + id);
      if (!el) return;
      const v = el.closest('.view');
      if (v) { if (location.hash.slice(1) !== v.dataset.view) history.replaceState(null, '', '#' + v.dataset.view); show(v.dataset.view); }
      const d = el.closest('details'); if (d) d.open = true;
      if (el.closest('#cardBank')) { location.hash = 'karten'; return; }
      if (el.closest('#quizBank')) { location.hash = 'quiz'; return; }
      el.scrollIntoView({ block: 'center' });
      el.classList.add('vorschau-mark'); setTimeout(() => el.classList.remove('vorschau-mark'), 1600);
    });
  }

  renderProgress();
  route();
})();
