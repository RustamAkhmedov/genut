// gen_Ut – Werkzeug-UI (Vanilla JS, kein Build).
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const app = $('#app');
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/* ---------------- API ---------------- */
async function api(method, path, body, roh = false) {
  const opt = { method, headers: {} };
  if (body instanceof FormData) opt.body = body;
  else if (body !== undefined) { opt.body = roh ? body : JSON.stringify(body); opt.headers['Content-Type'] = 'application/json'; }
  const r = await fetch('/api' + path, opt);
  let daten = null;
  try { daten = await r.json(); } catch (e) { /* kein JSON */ }
  if (!r.ok) {
    const d = daten && daten.detail;
    const err = new Error(typeof d === 'string' ? d : (d && d.fehler ? d.fehler.join('\n') : `HTTP ${r.status}`));
    err.detail = d; throw err;
  }
  return daten;
}

function toast(text, fehler = false) {
  const t = $('#toast');
  t.textContent = text; t.className = fehler ? 'fehler' : ''; t.hidden = false;
  clearTimeout(toast.t); toast.t = setTimeout(() => { t.hidden = true; }, fehler ? 6000 : 2600);
}

/** Eigener Bestätigungsdialog (statt window.confirm). */
function frage(titel, html, ja = 'OK', gefahr = false) {
  return new Promise((resolve) => {
    const d = $('#dlg'), f = $('#dlgForm');
    f.innerHTML = `<h2>${esc(titel)}</h2><div>${html}</div>
      <div class="reihe ende"><button class="btn" value="nein">Abbrechen</button><button class="btn ${gefahr ? 'gefahr' : 'primary'}" value="ja">${esc(ja)}</button></div>`;
    d.onclose = () => resolve(d.returnValue === 'ja');
    d.returnValue = ''; d.showModal();
  });
}

/* ---------------- Mini-Markdown für die Transkript-Vorschau ---------------- */
function mdHtml(md, bildUrl) {
  const tex = [];
  let s = md.replace(/\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)/g, (m) => { tex.push(m); return `\u0001${tex.length - 1}\u0001`; });
  const zeilen = s.split('\n');
  const out = []; let liste = null, absatz = [];
  const inline = (t) => esc(t)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/(^|\W)\*(.+?)\*/g, '$1<em>$2</em>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\[\?unleserlich\?\]/g, '<mark>unleserlich</mark>').replace(/\[\?\]/g, '<mark>?</mark>');
  const flush = () => { if (absatz.length) { out.push('<p>' + absatz.map(inline).join('<br>') + '</p>'); absatz = []; } if (liste) { out.push(`</${liste}>`); liste = null; } };
  const zellen = (z) => z.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim());
  for (let i = 0; i < zeilen.length; i++) {
    const z = zeilen[i];
    let m;
    if (/^\s*\|/.test(z) && /^\s*\|?\s*:?-{2,}/.test(zeilen[i + 1] || '')) {
      flush();
      const kopf = zellen(z); i += 2;
      const rows = [];
      while (i < zeilen.length && /^\s*\|/.test(zeilen[i])) rows.push(zellen(zeilen[i++]));
      i--;
      out.push('<table><thead><tr>' + kopf.map(c => `<th>${inline(c)}</th>`).join('') + '</tr></thead><tbody>' +
        rows.map(r => '<tr>' + r.map(c => `<td>${inline(c)}</td>`).join('') + '</tr>').join('') + '</tbody></table>');
      continue;
    }
    if ((m = /^\[\[SKIZZE (.*)\]\]\s*$/.exec(z.trim()))) {
      flush();
      const foto = (/foto=(\S+)/.exec(m[1]) || [])[1], beschr = (/beschreibung="([^"]*)"/.exec(m[1]) || [])[1] || m[1];
      out.push(foto && bildUrl ? `<figure class="skizze skizze-bild"><img src="${esc(bildUrl(foto))}" alt="" loading="lazy"><figcaption>${esc(beschr)}</figcaption></figure>`
        : `<div class="skizze">Skizze: ${esc(m[1])}</div>`);
      continue;
    }
    if ((m = /^(#{1,4})\s+(.*)$/.exec(z))) { flush(); out.push(`<h${m[1].length + 1}>${inline(m[2])}</h${m[1].length + 1}>`); continue; }
    if ((m = /^\s*([-*]|\d+[.)])\s+(.*)$/.exec(z))) {
      if (absatz.length) { out.push('<p>' + absatz.map(inline).join('<br>') + '</p>'); absatz = []; }
      const typ = /\d/.test(m[1]) ? 'ol' : 'ul';
      if (liste !== typ) { if (liste) out.push(`</${liste}>`); out.push(`<${typ}>`); liste = typ; }
      out.push(`<li>${inline(m[2])}</li>`); continue;
    }
    if (!z.trim()) { flush(); continue; }
    if (liste) { out.push(`</${liste}>`); liste = null; }
    absatz.push(z);
  }
  flush();
  return out.join('\n').replace(/\u0001(\d+)\u0001/g, (_, i) => esc(tex[+i]));
}
// Überschriften und Abschnitte (gleiche Regeln wie genut/einlesen.py: ueberschriften/abschnitte_filtern)
function ueberschriftenListe(md) {
  const zeilen = md.split('\n'), out = []; let code = false;
  zeilen.forEach((z, i) => {
    if (z.trim().startsWith('```')) { code = !code; return; }
    const m = !code && /^(#{1,6})\s+(.+?)\s*#*\s*$/.exec(z);
    if (m) out.push({ zeile: i, ebene: m[1].length, text: m[2].trim() });
  });
  out.forEach((u, k) => {
    const n = out.slice(k + 1).find(x => x.ebene <= u.ebene);
    u.ende = n ? n.zeile : zeilen.length;
    u.zeichen = zeilen.slice(u.zeile + 1, u.ende).join('').length;
  });
  return out;
}
function abschnitteFiltern(md, aus) {
  if (!aus.length) return md;
  const zeilen = md.split('\n'), weg = new Set(aus), behalten = zeilen.map(() => true);
  ueberschriftenListe(md).forEach(u => { if (weg.has(u.text)) for (let i = u.zeile; i < u.ende; i++) behalten[i] = false; });
  return zeilen.filter((_, i) => behalten[i]).join('\n');
}
// MathJax-Aufrufe nacheinander; Elemente, die inzwischen aus dem DOM entfernt wurden, überspringen
// (sonst misst MathJax in abgelösten Knoten und erzeugt SVGs mit NaN-Größen).
let mjKette = Promise.resolve();
function typeset(el) {
  if (!window.MathJax || !MathJax.typesetPromise) return mjKette;
  mjKette = mjKette.then(() => {
    if (!el.isConnected) return null;
    MathJax.typesetClear([el]);
    return MathJax.typesetPromise([el]);
  }).catch(() => { /* TeX-Fehler zeigt MathJax selbst an */ });
  return mjKette;
}

/* ---------------- Jobs (SSE) ---------------- */
function logZeile(logEl, e) {
  const div = document.createElement('div');
  const cls = e.typ === 'fehler' ? 'fehler' : e.typ === 'fertig' ? 'ok' : e.typ === 'fortschritt' ? 'f'
    : e.typ === 'pruefung' ? ({ ok: 'ok', fehler: 'fehler', nicht_pruefbar: 'warn' }[e.status] || '') : '';
  div.className = cls;
  div.textContent = (e.typ === 'fortschritt' ? '▸ ' : e.typ === 'pruefung' ? '  ' : '') + (e.text || e.typ);
  logEl.append(div); logEl.scrollTop = logEl.scrollHeight;
}
function jobVerfolgen(jobId, logEl, balken) {
  return new Promise((resolve) => {
    const es = new EventSource(`/api/jobs/${jobId}/events`);
    es.onmessage = (m) => {
      const e = JSON.parse(m.data);
      logZeile(logEl, e);
      if (balken && e.typ === 'fortschritt' && e.von) balken.style.width = Math.round((e.schritt - 1) / e.von * 100) + '%';
      if (e.typ === 'fertig' || e.typ === 'fehler') {
        if (balken) balken.style.width = e.typ === 'fertig' ? '100%' : balken.style.width;
        es.close(); resolve(e);
      }
    };
    es.onerror = () => { es.close(); resolve({ typ: 'fehler', text: 'Verbindung zum Server verloren' }); };
  });
}
async function jobStarten(slug, auftrag, logEl, balken) {
  logEl.hidden = false;
  const { job_id } = await api('POST', `/projekte/${slug}/jobs`, auftrag);
  return jobVerfolgen(job_id, logEl, balken);
}

/* ---------------- Fächer ---------------- */
let FAECHER = [];
async function faecherLaden() {
  if (!FAECHER.length) { try { FAECHER = await api('GET', '/faecher'); } catch (e) { FAECHER = [{ key: 'mathe', name: 'Mathematik', kurz: 'AM', profil: 'mathe_nw', profil_name: 'Mathematik & Naturwissenschaften' }]; } }
  return FAECHER;
}
const fachName = (k) => (FAECHER.find(f => f.key === k) || { name: k }).name;
function fachOptionen(gewaehlt) {
  const gruppen = {};
  FAECHER.filter(f => f.key !== 'sonstiges').forEach(f => { (gruppen[f.profil_name] = gruppen[f.profil_name] || []).push(f); });
  return Object.entries(gruppen).map(([g, fs]) => `<optgroup label="${esc(g)}">${fs.map(f => `<option value="${f.key}" ${f.key === gewaehlt ? 'selected' : ''}>${esc(f.name)}${f.kurz && f.kurz !== f.name ? ' (' + esc(f.kurz) + ')' : ''}</option>`).join('')}</optgroup>`).join('') +
    `<option value="sonstiges" ${gewaehlt === 'sonstiges' ? 'selected' : ''}>Sonstiges</option>`;
}

/* ---------------- KI-Version (aus config.toml) ---------------- */
const MODELL_NAME = { claude_code: 'Claude', gemini: 'Gemini', ollama: 'Lokal (Ollama)' };
let KI = { standard: 'claude_code', auswahl: ['claude_code', 'gemini'], gemini_schluessel: false, pages: false };
async function kiLaden() {
  try { KI = await api('GET', '/ki'); } catch (e) { /* Standardwerte */ }
  return KI;
}
const modellOptionen = (gewaehlt) => [...new Set([...KI.auswahl, gewaehlt])].filter(Boolean)
  .map(m => `<option value="${m}" ${m === gewaehlt ? 'selected' : ''}>${esc(MODELL_NAME[m] || m)}</option>`).join('');

/* ---------------- Router ---------------- */
async function route() {
  await faecherLaden();
  const teile = location.hash.replace(/^#\/?/, '').split('/').filter(Boolean);
  try {
    if (!teile.length) return await seiteProjekte();
    if (teile[0] === 'einstellungen') return await seiteEinstellungen();
    if (teile[0] === 'p' && teile[1]) return await seiteProjekt(teile[1], teile[2], teile[3]);
    location.hash = '#/';
  } catch (e) {
    app.innerHTML = `<div class="karte eng"><h2>Fehler</h2><p>${esc(e.message)}</p><a href="#/">Zur Übersicht</a></div>`;
  }
}
window.addEventListener('hashchange', route);

/* ---------------- KI-Schalter (Kopfzeile) ----------------
   Außerhalb eines Projekts: Standard für neue Projekte. In einem Projekt: zusätzlich die KI dieses Projekts. */
function aktuellesProjekt() {
  const t = location.hash.replace(/^#\/?/, '').split('/');
  return t[0] === 'p' && t[1] ? t[1] : null;
}

async function kiSchalterZeigen() {
  let wert = null, status = null;
  try {
    status = await api('GET', '/ki');
    wert = status.standard;
    const slug = aktuellesProjekt();
    if (slug) wert = (await api('GET', `/projekte/${slug}`)).modell;
  } catch (e) { return; }
  kiSchalterZeigen.status = status; KI = status;
  const s = $('.ki-schalter');
  const optionen = [...new Set([...status.auswahl, wert])].filter(Boolean);
  s.hidden = optionen.length < 2;
  s.querySelectorAll('[data-ki]').forEach(b => b.remove());
  for (const m of optionen) {
    const b = document.createElement('button');
    b.type = 'button'; b.setAttribute('role', 'radio'); b.dataset.ki = m; b.textContent = (MODELL_NAME[m] || m).replace(' (Ollama)', '');
    b.addEventListener('click', () => kiWaehlen(m));
    s.appendChild(b);
  }
  document.querySelectorAll('.ki-schalter [data-ki]').forEach(b => {
    const an = b.dataset.ki === wert;
    b.classList.toggle('an', an); b.setAttribute('aria-checked', an ? 'true' : 'false');
  });
  s.title = aktuellesProjekt() ? 'KI für dieses Projekt (und Standard für neue Projekte)' : 'KI für neue Projekte';
}

async function kiWaehlen(ki) {
  const slug = aktuellesProjekt();
  try {
    if (ki === 'gemini' && kiSchalterZeigen.status && !kiSchalterZeigen.status.gemini_schluessel) {
      toast('Kein Gemini-Schlüssel: GEMINI_API_KEY in die Datei .env im gen_Ut-Ordner schreiben', true);
    }
    await api('PUT', '/ki', { standard: ki });
    if (slug) await api('PATCH', `/projekte/${slug}`, { modell: ki });
    toast(`KI: ${MODELL_NAME[ki] || ki}${slug ? ' (dieses Projekt + neue Projekte)' : ' (neue Projekte)'}`);
    if (slug) await route();
    await kiSchalterZeigen();
  } catch (e) { toast(e.message, true); }
}
window.addEventListener('hashchange', kiSchalterZeigen);
kiSchalterZeigen();

/* ---------------- Projekte ---------------- */
const STATUS_CHIP = { hochgeladen: '', transkribiert: 'warn', kontrolliert: 'akz', verarbeitet: 'ok' };

async function seiteProjekte() {
  const liste = await api('GET', '/projekte');
  app.innerHTML = `<div class="eng">
    <div class="kopfzeile"><h1>Projekte</h1><button class="btn primary" id="neuBtn">Neues Projekt</button></div>
    <div class="projekte">${liste.map(p => `
      <a class="karte projekt" href="#/p/${esc(p.slug)}">
        <h3>${esc(p.name)}</h3>
        <div class="reihe"><span class="chip">${esc(fachName(p.fach))}</span><span class="chip">${p.fotos.length} Foto${p.fotos.length === 1 ? '' : 's'}</span>
          ${p.zahlen ? `<span class="chip">${p.zahlen.themen} Themen · ${p.zahlen.aufgaben} Aufgaben · ${p.zahlen.quiz || 0} Quizfragen</span>` : ''}
          ${p.pages.veroeffentlicht ? '<span class="chip ok">online</span>' : ''}${p.laeuft ? '<span class="chip akz">läuft …</span>' : ''}</div>
        <span class="muted klein">${p.letzter_build ? 'Zuletzt gebaut ' + new Date(p.letzter_build).toLocaleString('de-AT') : 'Noch nicht gebaut'}</span>
      </a>`).join('') || '<p class="leer">Noch keine Projekte. Leg eines an und lade Fotos hoch.</p>'}
    </div></div>`;
  $('#neuBtn').onclick = neuesProjekt;
}

async function neuesProjekt() {
  const standard = (await kiLaden()).standard;
  const d = $('#dlg'), f = $('#dlgForm');
  f.innerHTML = `<h2>Neues Projekt</h2>
    <label class="feld">Name<input type="text" name="name" required placeholder="z. B. Integralrechnung" autofocus></label>
    <div class="raster raster-2">
      <label class="feld">Fach<select name="fach">${fachOptionen('mathe')}</select></label>
      <label class="feld">Modell<select name="modell">
        ${modellOptionen(standard)}</select></label>
      <label class="feld">Probeaufgaben je Thema<input type="number" name="probe" min="0" max="5" value="2"></label>
      <label class="feld">Karteikarten<select name="karten"><option value="auto">automatisch</option>${[2, 3, 4, 5, 6, 8].map(n => `<option value="${n}">${n} je Thema</option>`).join('')}</select></label>
      <label class="feld">Quizfragen je Thema<input type="number" name="quiz" min="0" max="10" value="5"></label>
      <label class="feld">Erklärstil<select name="stil"><option value="knapp">knapp</option><option value="ausfuehrlich">ausführlich</option></select></label>
      <label class="feld">Max. Korrekturrunden<input type="number" name="runden" min="0" max="5" value="3"></label>
    </div>
    <div class="reihe ende"><button class="btn" value="nein" formnovalidate>Abbrechen</button><button class="btn primary" value="ja">Anlegen</button></div>`;
  d.returnValue = '';
  d.onclose = async () => {
    if (d.returnValue !== 'ja') return;
    const fd = new FormData(f);
    try {
      const p = await api('POST', '/projekte', {
        name: fd.get('name'), fach: fd.get('fach'), modell: fd.get('modell'),
        einstellungen: {
          probeaufgaben_pro_thema: +fd.get('probe'), karten: fd.get('karten') === 'auto' ? 'auto' : +fd.get('karten'),
          erklaerstil: fd.get('stil'), max_korrekturrunden: +fd.get('runden'), quiz_pro_thema: +fd.get('quiz')
        }
      });
      location.hash = `#/p/${p.slug}/fotos`;
    } catch (e) { toast(e.message, true); }
  };
  d.showModal();
}

/* ---------------- Projekt ---------------- */
const SCHRITTE = [['fotos', 'Fotos'], ['transkripte', 'Transkripte'], ['generieren', 'Generieren'], ['vorschau', 'Vorschau'], ['export', 'Export']];

async function seiteProjekt(slug, tab, extra) {
  const p = await api('GET', `/projekte/${slug}`);
  // Fertig gebaute Projekte öffnen direkt in der Vorschau (zum Üben), neue bei den Fotos.
  if (!tab) tab = p.hat_seite ? 'vorschau' : 'fotos';
  app.innerHTML = `
    <div class="kopfzeile"><div><div class="eyebrow">${esc(fachName(p.fach))} · ${esc(MODELL_NAME[p.modell] || p.modell)}</div><h1>${esc(p.name)}</h1></div>
      <div class="reihe"><button class="btn klein" id="einstBtn">Einstellungen</button><button class="btn klein gefahr" id="delBtn">Löschen</button></div></div>
    <nav class="stepper" aria-label="Schritte">${SCHRITTE.map(([k, l], i) => `<a href="#/p/${slug}/${k}" ${k === tab ? 'aria-current="step"' : ''}><span class="n">${i + 1}</span>${l}</a>`).join('')}</nav>
    <section id="inhalt"></section>`;
  $('#delBtn').onclick = async () => {
    if (await frage('Projekt löschen?', `<p>„${esc(p.name)}“ wird in den Papierkorb (<code>projekte/.geloescht/</code>) verschoben.</p>`, 'Löschen', true)) {
      try { await api('DELETE', `/projekte/${slug}`); location.hash = '#/'; } catch (e) { toast(e.message, true); }
    }
  };
  $('#einstBtn').onclick = () => projektEinstellungen(p);
  const ziel = $('#inhalt');
  const fn = { fotos: tabFotos, transkripte: tabTranskripte, generieren: tabGenerieren, vorschau: tabVorschau, export: tabExport }[tab] || tabFotos;
  await fn(p, ziel, extra);
}

function projektEinstellungen(p) {
  const d = $('#dlg'), f = $('#dlgForm'), e = p.einstellungen;
  f.innerHTML = `<h2>Einstellungen</h2><div class="raster raster-2">
    <label class="feld">Modell<select name="modell">${modellOptionen(p.modell)}</select></label>
    <label class="feld">Probeaufgaben je Thema<input type="number" name="probe" min="0" max="5" value="${e.probeaufgaben_pro_thema}"></label>
    <label class="feld">Karteikarten<input type="text" name="karten" value="${esc(e.karten)}"><span class="hilfe">„auto“ oder Zahl je Thema</span></label>
    <label class="feld">Quizfragen je Thema<input type="number" name="quiz" min="0" max="10" value="${e.quiz_pro_thema ?? 5}"></label>
    <label class="feld">Erklärstil<select name="stil"><option value="knapp" ${e.erklaerstil === 'knapp' ? 'selected' : ''}>knapp</option><option value="ausfuehrlich" ${e.erklaerstil === 'ausfuehrlich' ? 'selected' : ''}>ausführlich</option></select></label>
    <label class="feld">Max. Korrekturrunden<input type="number" name="runden" min="0" max="5" value="${e.max_korrekturrunden}"></label></div>
    <div class="reihe ende"><button class="btn" value="nein">Abbrechen</button><button class="btn primary" value="ja">Speichern</button></div>`;
  d.returnValue = '';
  d.onclose = async () => {
    if (d.returnValue !== 'ja') return;
    const fd = new FormData(f);
    const k = String(fd.get('karten')).trim();
    try {
      await api('PATCH', `/projekte/${p.slug}`, { modell: fd.get('modell'), einstellungen: {
        probeaufgaben_pro_thema: +fd.get('probe'), karten: k === 'auto' ? 'auto' : +k, erklaerstil: fd.get('stil'), max_korrekturrunden: +fd.get('runden'),
        quiz_pro_thema: +fd.get('quiz') } });
      toast('Gespeichert'); route();
    } catch (err) { toast(err.message, true); }
  };
  d.showModal();
}

/* ---------------- Tab: Fotos ---------------- */
async function tabFotos(p, ziel) {
  const neu = p.fotos.filter(f => f.status === 'hochgeladen').length;
  ziel.innerHTML = `
    <label class="drop" id="drop" tabindex="0">
      <input type="file" id="datei" multiple accept=".jpg,.jpeg,.png,.webp,.heic,.heif,image/*,.pdf,.docx,.pptx,.html,.htm,.md,.markdown,.txt" hidden>
      <strong>Fotos oder Dateien hierher ziehen</strong> oder klicken zum Auswählen<br><span class="klein">Fotos: JPG, PNG, WebP, HEIC · Dateien: PDF, Word (.docx), PowerPoint (.pptx), gespeicherte Webseiten (.html), Markdown, Text · Reihenfolge per Ziehen ändern</span>
    </label>
    <div class="fotos" id="fotos">${p.fotos.map(f => `
      <div class="foto" draggable="true" data-datei="${esc(f.datei)}">
        ${f.art === 'dokument' ? `<div class="dok-kachel" title="${esc(f.original)}"><span class="dok-typ">${esc(f.datei.split('.').pop().toUpperCase())}</span><span class="dok-name">${esc(f.original)}</span></div>`
          : `<img src="/api/projekte/${p.slug}/fotos/${esc(f.datei)}" alt="${esc(f.original)}" loading="lazy" title="${esc(f.original)}">`}
        <div class="fu"><span class="chip ${STATUS_CHIP[f.status]}">${esc(f.status)}</span><span class="muted klein" title="${esc(f.original)}">${esc(f.datei)}</span>
          ${f.status !== 'verarbeitet' ? `<button class="btn klein gefahr" data-del="${esc(f.datei)}" style="margin-left:auto" aria-label="Löschen">✕</button>` : ''}</div>
      </div>`).join('')}</div>
    ${p.fotos.filter(f => f.hinweise && f.hinweise.length && f.status !== 'verarbeitet').map(f => `<div class="hinweis-box"><strong>${esc(f.original)}:</strong> ${f.hinweise.map(esc).join(' ')}</div>`).join('')}
    <div class="reihe abstand"><button class="btn primary" id="tkBtn" ${neu ? '' : 'disabled'}>Transkribieren (${neu})</button>
      <a class="btn" href="#/p/${p.slug}/transkripte">Weiter zu den Transkripten</a></div>
    <div class="fortschritt" hidden id="fbar"><span></span></div>
    <div class="log abstand" id="log" hidden></div>`;
  const drop = $('#drop'), input = $('#datei');
  const hoch = async (files) => {
    if (!files.length) return;
    const fd = new FormData();
    for (const f of files) fd.append('dateien', f);
    drop.innerHTML = '<strong>Lade hoch …</strong>';
    try {
      const r = await api('POST', `/projekte/${p.slug}/fotos`, fd);
      const dok = r.neu.filter(f => f.art === 'dokument').length, foto = r.neu.length - dok;
      toast([dok ? `${dok} Datei(en) eingelesen` : '', foto ? `${foto} Foto(s)/Seite(n) zum Transkribieren` : ''].filter(Boolean).join(' · '));
    }
    catch (e) { toast(e.message, true); }
    route();
  };
  input.onchange = () => hoch(Array.from(input.files));
  drop.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } });
  drop.addEventListener('dragover', (e) => { if (e.dataTransfer.types.includes('Files')) { e.preventDefault(); drop.classList.add('ueber'); } });
  drop.addEventListener('dragleave', () => drop.classList.remove('ueber'));
  drop.addEventListener('drop', (e) => { e.preventDefault(); drop.classList.remove('ueber'); hoch(Array.from(e.dataTransfer.files)); });

  $$('[data-del]').forEach(b => b.onclick = async (e) => {
    e.preventDefault();
    if (!await frage('Löschen?', `<p>${esc(b.dataset.del)} und das Transkript werden gelöscht.</p>`, 'Löschen', true)) return;
    try { await api('DELETE', `/projekte/${p.slug}/fotos/${b.dataset.del}`); route(); } catch (err) { toast(err.message, true); }
  });

  // Umsortieren per Drag & Drop
  let gezogen = null;
  $$('.foto').forEach(el => {
    el.addEventListener('dragstart', (e) => { gezogen = el; el.classList.add('zieh'); e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', el.dataset.datei); });
    el.addEventListener('dragend', () => el.classList.remove('zieh'));
    el.addEventListener('dragover', (e) => { if (gezogen) { e.preventDefault(); const r = el.getBoundingClientRect(); el.parentNode.insertBefore(gezogen, e.clientX < r.left + r.width / 2 ? el : el.nextSibling); } });
    el.addEventListener('drop', async (e) => {
      if (!gezogen) return;
      e.preventDefault(); e.stopPropagation(); gezogen = null;
      try { await api('PATCH', `/projekte/${p.slug}/fotos`, { reihenfolge: $$('.foto').map(x => x.dataset.datei) }); toast('Reihenfolge gespeichert'); }
      catch (err) { toast(err.message, true); route(); }
    });
  });

  const fbar = $('#fbar');
  const starte = async (auftrag) => {
    $('#tkBtn').disabled = true; fbar.hidden = false;
    const e = await jobStarten(p.slug, auftrag, $('#log'), $('span', fbar));
    toast(e.typ === 'fertig' ? 'Transkription fertig' : e.text, e.typ !== 'fertig');
    if (e.typ === 'fertig') setTimeout(() => { location.hash = `#/p/${p.slug}/transkripte`; }, 800);
  };
  $('#tkBtn').onclick = () => starte({ art: 'transkribieren' }).catch(e => toast(e.message, true));
  if (p.laeuft) { fbar.hidden = false; $('#log').hidden = false; jobVerfolgen(p.laeuft, $('#log'), $('span', fbar)).then(() => route()); }
}

/* ---------------- Tab: Transkripte ---------------- */
async function tabTranskripte(p, ziel, auswahl) {
  const fotos = p.fotos.filter(f => f.status !== 'hochgeladen');
  if (!fotos.length) {
    ziel.innerHTML = `<p class="leer">Noch keine Transkripte. <a href="#/p/${p.slug}/fotos">Fotos hochladen und transkribieren</a>.</p>`;
    return;
  }
  const offen = fotos.filter(f => f.status !== 'verarbeitet');
  const akt = fotos.find(f => f.datei === auswahl) || offen[0] || fotos[0];
  const alleKontrolliert = offen.length > 0 && offen.every(f => f.status === 'kontrolliert');
  ziel.innerHTML = `
    <div class="kopfzeile">
      <div class="tk-liste">${fotos.map(f => `<a class="btn klein" href="#/p/${p.slug}/transkripte/${esc(f.datei)}" ${f === akt ? 'style="border-color:var(--accent);color:var(--accent)"' : ''}>${esc(f.datei)} <span class="chip ${STATUS_CHIP[f.status]}">${f.status === 'kontrolliert' ? '✓' : f.status === 'verarbeitet' ? 'fertig' : 'offen'}</span></a>`).join('')}</div>
      <a class="btn primary" href="#/p/${p.slug}/generieren" ${alleKontrolliert ? '' : 'aria-disabled="true" style="opacity:.45;pointer-events:none"'}>Weiter zum Generieren</a>
    </div>
    <div class="tk">
      <div class="tk-links">${akt.art === 'dokument'
        ? `<div class="dok-info"><div class="eyebrow">Datei</div><strong>${esc(akt.original)}</strong><p class="muted klein">Ohne KI eingelesen. Bitte kurz prüfen und Themen abwählen, die nicht auf die Lernseite sollen.</p><div id="tkHinweise"></div></div>`
        : `<div class="viewer" id="viewer"><div class="flaeche" id="flaeche"><img id="bild" src="/api/projekte/${p.slug}/fotos/${esc(akt.datei)}" alt="Foto ${esc(akt.datei)}"></div><span class="viewer-hilfe">Mausrad: Zoom · Ziehen: Verschieben · Doppelklick: zurücksetzen</span></div>`}
        <details class="themen-wahl" id="themenWahl" ${akt.art === 'dokument' ? 'open' : ''}><summary>Themenauswahl <span class="muted klein" id="themenZahl"></span></summary>
          <div class="reihe klein"><button class="btn klein" id="alleThemen" type="button">Alle</button><button class="btn klein" id="keineThemen" type="button">Keine</button></div>
          <div id="themenListe" class="themen-liste"></div></details>
        <div id="dokBilder" class="dok-bilder"></div>
      </div>
      <div><textarea id="md" spellcheck="false" aria-label="Transkript" ${akt.status === 'verarbeitet' ? 'readonly' : ''}></textarea></div>
      <div><div class="vorschau" id="vs"></div></div>
    </div>
    <div class="reihe abstand">
      ${akt.status === 'verarbeitet' ? '<span class="muted">Dieses Foto ist schon verarbeitet – das Transkript ist nur zur Ansicht.</span>' : `
      <button class="btn" id="speichern">Speichern</button>
      <button class="btn" id="neuTk">${akt.art === 'dokument' ? 'Neu einlesen' : 'Neu transkribieren'}</button>
      <button class="btn primary" id="ok">${akt.status === 'kontrolliert' ? 'Kontrolliert ✓ (speichern)' : 'Kontrolliert ✓'}</button>`}
      <span class="muted klein" id="status"></span>
    </div>
    <div class="log abstand" id="log" hidden></div>`;

  const info = await api('GET', `/projekte/${p.slug}/transkripte/${akt.datei}`);
  const ta = $('#md'), vs = $('#vs');
  ta.value = info.md;
  let geaendert = false;
  let aus = new Set(info.ausgeschlossen || []);
  const bildUrl = (d) => `/api/projekte/${p.slug}/fotos/${encodeURIComponent(d)}`;
  if ($('#tkHinweise')) $('#tkHinweise').innerHTML = (info.hinweise || []).map(h => `<div class="hinweis-box">${esc(h)}</div>`).join('');
  if (info.bilder && info.bilder.length) $('#dokBilder').innerHTML = `<div class="eyebrow">${info.bilder.length} Bild(er) aus der Datei</div><div class="dok-bild-raster">` +
    info.bilder.map(b => `<img src="${bildUrl(b)}" alt="${esc(b)}" title="${esc(b)}" loading="lazy">`).join('') + '</div>';
  // Themenauswahl: abgewählte Abschnitte gehen nicht an die KI (der Text bleibt erhalten)
  const themenZeichnen = () => {
    const us = ueberschriftenListe(ta.value);
    $('#themenZahl').textContent = us.length ? `${us.length - [...aus].filter(a => us.some(u => u.text === a)).length} von ${us.length} gewählt` : '(keine Überschriften)';
    $('#themenWahl').hidden = !us.length;
    // Unterthemen eines abgewählten Themas fallen mit weg → ausgegraut anzeigen
    const durchEltern = us.map(u => us.some(v => aus.has(v.text) && v.zeile < u.zeile && u.zeile < v.ende && v.ebene < u.ebene));
    $('#themenListe').innerHTML = us.map((u, i) => `<label class="thema-zeile${durchEltern[i] ? ' gesperrt' : ''}" style="padding-left:${(u.ebene - Math.min(...us.map(x => x.ebene))) * 16 + 4}px"${durchEltern[i] ? ' title="Fällt mit dem übergeordneten Thema weg"' : ''}>
      <input type="checkbox" data-thema="${i}" ${aus.has(u.text) || durchEltern[i] ? '' : 'checked'} ${akt.status === 'verarbeitet' || durchEltern[i] ? 'disabled' : ''}>
      <span>${esc(u.text)}</span><span class="muted klein">${u.zeichen > 999 ? Math.round(u.zeichen / 100) / 10 + 'k' : u.zeichen} Z.</span></label>`).join('');
    $$('#themenListe input').forEach(cb => cb.onchange = () => {
      const u = us[+cb.dataset.thema];
      if (cb.checked) aus.delete(u.text); else aus.add(u.text);
      geaendert = true; $('#status').textContent = 'ungespeichert'; themenZeichnen(); vorschau();
    });
  };
  const alleSetzen = (an) => { aus = an ? new Set() : new Set(ueberschriftenListe(ta.value).map(u => u.text)); geaendert = true; themenZeichnen(); vorschau(); };
  $('#alleThemen').onclick = () => alleSetzen(true);
  $('#keineThemen').onclick = () => alleSetzen(false);
  // Zoombares Foto mit bbox-Overlay (nur bei Fotos)
  const viewer = $('#viewer') || document.createElement('div'), flaeche = $('#flaeche') || document.createElement('div'), bild = $('#bild') || new Image();
  let z = 1, x = 0, y = 0, start = null;
  const anwenden = () => { flaeche.style.transform = `translate(${x}px,${y}px) scale(${z})`; };
  const einpassen = () => { const s = viewer.clientWidth / (bild.naturalWidth || 1); z = Math.min(1, s); x = 0; y = 0; anwenden(); };
  bild.onload = () => { bild.width = bild.naturalWidth; einpassen(); boxen(); };
  viewer.addEventListener('wheel', (e) => {
    e.preventDefault();
    const r = viewer.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
    const nz = Math.min(6, Math.max(0.1, z * (e.deltaY < 0 ? 1.15 : 1 / 1.15)));
    x = mx - (mx - x) * nz / z; y = my - (my - y) * nz / z; z = nz; anwenden();
  }, { passive: false });
  const zeiger = new Map(); let pinch = null;
  viewer.addEventListener('pointerdown', (e) => { viewer.setPointerCapture(e.pointerId); zeiger.set(e.pointerId, e); start = { px: e.clientX, py: e.clientY, x, y }; });
  viewer.addEventListener('pointermove', (e) => {
    if (!zeiger.has(e.pointerId)) return;
    zeiger.set(e.pointerId, e);
    if (zeiger.size === 2) {
      const [a, b] = Array.from(zeiger.values());
      const d = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
      if (pinch) { z = Math.min(6, Math.max(0.1, pinch.z * d / pinch.d)); anwenden(); } else pinch = { d, z };
      return;
    }
    if (start) { x = start.x + e.clientX - start.px; y = start.y + e.clientY - start.py; anwenden(); }
  });
  const ende = (e) => { zeiger.delete(e.pointerId); if (zeiger.size < 2) pinch = null; if (!zeiger.size) start = null; };
  viewer.addEventListener('pointerup', ende); viewer.addEventListener('pointercancel', ende);
  viewer.addEventListener('dblclick', einpassen);
  function boxen() {
    $$('.bbox', flaeche).forEach(b => b.remove());
    const W = bild.naturalWidth, H = bild.naturalHeight;
    for (const m of ta.value.matchAll(/\[\[SKIZZE ([^\]]*)\]\]/g)) {
      const bb = /bbox=([\d.]+),([\d.]+),([\d.]+),([\d.]+)/.exec(m[1]);
      if (!bb) continue;
      const art = (/art=(\w+)/.exec(m[1]) || [])[1] || 'skizze';
      const d = document.createElement('div'); d.className = 'bbox';
      Object.assign(d.style, { left: bb[1] * W + 'px', top: bb[2] * H + 'px', width: bb[3] * W + 'px', height: bb[4] * H + 'px' });
      d.innerHTML = `<span>${esc(art)}</span>`; flaeche.append(d);
    }
  }
  let t = null;
  const vorschau = () => {
    const n = [...aus].filter(a => ueberschriftenListe(ta.value).some(u => u.text === a)).length;
    vs.innerHTML = (n ? `<p class="hinweis-box klein">${n} Abschnitt(e) abgewählt – sie gehen nicht an die KI.</p>` : '') + mdHtml(abschnitteFiltern(ta.value, [...aus]), bildUrl);
    typeset(vs); boxen();
  };
  ta.addEventListener('input', () => { geaendert = true; $('#status').textContent = 'ungespeichert'; clearTimeout(t); t = setTimeout(() => { vorschau(); themenZeichnen(); }, 300); });
  themenZeichnen();
  if (window.MathJax && MathJax.startup && MathJax.startup.promise) MathJax.startup.promise.then(vorschau); else window.addEventListener('load', vorschau);
  vorschau();

  if (akt.status === 'verarbeitet') return;
  const speichern = async (kontrolliert) => {
    try {
      const gueltig = new Set(ueberschriftenListe(ta.value).map(u => u.text));
      await api('PUT', `/projekte/${p.slug}/transkripte/${akt.datei}`, { md: ta.value, kontrolliert, ausgeschlossen: [...aus].filter(a => gueltig.has(a)) });
      geaendert = false; toast(kontrolliert ? 'Als kontrolliert markiert' : 'Gespeichert');
      if (kontrolliert) {
        const naechstes = offen.find(f => f.datei !== akt.datei && f.status !== 'kontrolliert');
        location.hash = naechstes ? `#/p/${p.slug}/transkripte/${naechstes.datei}` : `#/p/${p.slug}/transkripte/${akt.datei}`;
        if (!naechstes) route();
      } else $('#status').textContent = 'gespeichert';
    } catch (e) { toast(e.message, true); }
  };
  $('#speichern').onclick = () => speichern(akt.status === 'kontrolliert');
  $('#ok').onclick = () => speichern(true);
  $('#neuTk').onclick = async () => {
    if (geaendert && !await frage(akt.art === 'dokument' ? 'Neu einlesen?' : 'Neu transkribieren?', '<p>Deine ungespeicherten Änderungen gehen verloren.</p>', 'Ja', true)) return;
    $('#neuTk').disabled = true;
    if (akt.art === 'dokument') {
      try { await api('POST', `/projekte/${p.slug}/dokumente/${akt.datei}/neu_einlesen`); toast('Neu eingelesen'); geaendert = false; route(); }
      catch (err) { toast(err.message, true); $('#neuTk').disabled = false; }
      return;
    }
    try {
      const e = await jobStarten(p.slug, { art: 'transkribieren', dateien: [akt.datei] }, $('#log'));
      toast(e.typ === 'fertig' ? 'Neu transkribiert' : e.text, e.typ !== 'fertig'); route();
    } catch (err) { toast(err.message, true); $('#neuTk').disabled = false; }
  };
  window.onbeforeunload = () => (geaendert ? true : undefined);
}

/* ---------------- Tab: Generieren ---------------- */
async function tabGenerieren(p, ziel) {
  const bereit = p.fotos.filter(f => f.status === 'kontrolliert');
  const offen = p.fotos.filter(f => f.status === 'transkribiert' || f.status === 'hochgeladen');
  const e = p.einstellungen;
  ziel.innerHTML = `<div class="eng">
    <div class="karte">
      <h2>Lernseite generieren</h2>
      <p>${bereit.length ? `<strong>${bereit.length} kontrollierte${bereit.length === 1 ? 's Foto' : ' Fotos'}</strong> werden verarbeitet${p.zahlen ? ' und in die bestehende Seite eingefügt (Bestehendes bleibt unverändert)' : ''}.` : 'Keine kontrollierten Fotos bereit.'}
      ${offen.length ? `<br><span class="muted">${offen.length} Foto(s) sind noch nicht kontrolliert und werden übersprungen.</span>` : ''}</p>
      <p class="muted klein">Probeaufgaben je Thema: ${e.probeaufgaben_pro_thema} · Quizfragen: ${e.quiz_pro_thema ?? 5} · Karten: ${esc(e.karten)} · Stil: ${e.erklaerstil} · bis zu ${e.max_korrekturrunden} Korrekturrunden. Das dauert mit Claude Code meist 2–6 Minuten.</p>
      <div class="reihe"><button class="btn primary" id="gen" ${bereit.length && !p.laeuft ? '' : 'disabled'}>Generieren</button>
        <button class="btn" id="bauen" ${p.zahlen && !p.laeuft ? '' : 'disabled'} title="Alles neu prüfen und bauen, ohne KI">Nur neu prüfen &amp; bauen</button></div>
      <div class="fortschritt" id="fbar" hidden><span></span></div>
    </div>
    <div class="log abstand" id="log" hidden></div>
    <div class="karte abstand" id="zus" hidden></div></div>`;
  const fbar = $('#fbar');
  const fertig = (ev) => {
    const z = $('#zus');
    if (ev.typ === 'fertig' && ev.ergebnis) {
      const s = ev.ergebnis.status || {};
      z.hidden = false;
      z.innerHTML = `<h3>Fertig</h3><p>${ev.ergebnis.neu !== undefined ? `<strong>${ev.ergebnis.neu}</strong> Elemente neu · ` : ''}
        <span class="chip ok">${s.ok || 0} geprüft ✓</span> <span class="chip">${s.ungeprueft || 0} ohne Prüfbedarf</span>
        <span class="chip warn">${s.nicht_pruefbar || 0} ungeprüft</span> <span class="chip err">${s.fehler || 0} mit ⚠</span>
        ${ev.ergebnis.runden ? ` · ${ev.ergebnis.runden} Korrekturrunde(n)` : ''}</p>
        <a class="btn primary" href="#/p/${p.slug}/vorschau">Zur Vorschau</a>`;
    } else toast(ev.text, true);
    $('#gen').disabled = true;
  };
  const los = async (art) => {
    $('#gen').disabled = $('#bauen').disabled = true; fbar.hidden = false;
    try { fertig(await jobStarten(p.slug, { art }, $('#log'), $('span', fbar))); } catch (err) { toast(err.message, true); }
  };
  $('#gen').onclick = () => los('generieren');
  $('#bauen').onclick = () => los('pruefen_bauen');
  if (p.laeuft) { fbar.hidden = false; $('#log').hidden = false; jobVerfolgen(p.laeuft, $('#log'), $('span', fbar)).then(fertig); }
}

/* ---------------- Diagramme: Mermaid in der Vorschau zeichnen ---------------- */
// Mermaid braucht einen echten Browser. Die Tool-Vorschau zeichnet daher alle Diagramme ohne SVG
// (hell + dunkel), schickt sie an den Server und lässt die Seite neu bauen. Die Lernseite selbst
// enthält danach nur fertige SVGs.
let mermaidLaden = null;
function mermaidHolen() {
  if (!mermaidLaden) mermaidLaden = new Promise((ok, fehler) => {
    const s = document.createElement('script'); s.src = '/mermaid.js';
    s.onload = () => ok(window.mermaid); s.onerror = () => fehler(new Error('mermaid.js nicht gefunden (npm install?)'));
    document.head.appendChild(s);
  });
  return mermaidLaden;
}
const MERMAID_THEMES = {
  hell: { darkMode: false, background: 'transparent', fontFamily: 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif', fontSize: '15px',
    primaryColor: '#efe6d6', primaryBorderColor: '#a8482a', primaryTextColor: '#2b231d', secondaryColor: '#f6e3d9', tertiaryColor: '#fffcf6',
    lineColor: '#7d6f61', textColor: '#2b231d', noteBkgColor: '#f7ecd2', noteTextColor: '#2b231d', actorBkg: '#efe6d6', actorBorder: '#a8482a',
    signalColor: '#3a3029', labelBoxBkgColor: '#efe6d6', sectionBkgColor: '#efe6d6', altSectionBkgColor: '#fffcf6', taskBkgColor: '#a8482a',
    taskTextColor: '#fffaf4', taskBorderColor: '#8a3a22', gridColor: '#e0d4bf', doneTaskBkgColor: '#7d6f61', critBkgColor: '#b0393a',
    edgeLabelBackground: '#fffcf6', attributeBackgroundColorOdd: '#fffcf6', attributeBackgroundColorEven: '#f5efe4', clusterBkg: '#f5efe4', clusterBorder: '#e0d4bf' },
  dunkel: { darkMode: true, background: 'transparent', fontFamily: 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif', fontSize: '15px',
    primaryColor: '#2e2823', primaryBorderColor: '#e38b66', primaryTextColor: '#f1e8dc', secondaryColor: '#3b2820', tertiaryColor: '#241f1b',
    lineColor: '#a99a89', textColor: '#f1e8dc', noteBkgColor: '#3a2e15', noteTextColor: '#f1e8dc', actorBkg: '#2e2823', actorBorder: '#e38b66',
    signalColor: '#e3d8ca', labelBoxBkgColor: '#2e2823', sectionBkgColor: '#2e2823', altSectionBkgColor: '#241f1b', taskBkgColor: '#e38b66',
    taskTextColor: '#1b1714', taskBorderColor: '#e38b66', gridColor: '#3d352e', doneTaskBkgColor: '#a99a89', critBkgColor: '#ee8787',
    edgeLabelBackground: '#241f1b', attributeBackgroundColorOdd: '#241f1b', attributeBackgroundColorEven: '#2e2823', clusterBkg: '#2e2823', clusterBorder: '#3d352e' },
};
async function diagrammeZeichnen(slug, status) {
  let offen = [];
  try { offen = await api('GET', `/projekte/${slug}/diagramme/offen`); } catch (e) { return 0; }
  if (!offen.length) return 0;
  if (status) status(`Zeichne ${offen.length} Diagramm(e) …`);
  let mm;
  try { mm = await mermaidHolen(); } catch (e) { toast(e.message, true); return 0; }
  let n = 0;
  for (const d of offen) {
    const svgs = {};
    try {
      for (const art of ['hell', 'dunkel']) {
        mm.initialize({ startOnLoad: false, securityLevel: 'strict', theme: 'base', themeVariables: MERMAID_THEMES[art],
          htmlLabels: false, flowchart: { htmlLabels: false },
          gantt: { useWidth: 720, todayMarker: 'off', axisFormat: '%d.%m.', fontSize: 13, sectionFontSize: 13, barHeight: 24, barGap: 6 } });
        const { svg } = await mm.render(`dg-${d.hash}-${art}`, d.quelle);
        svgs[art] = svg;
      }
      await api('PUT', `/projekte/${slug}/diagramme/${d.hash}`, svgs);
    } catch (e) {
      await api('PUT', `/projekte/${slug}/diagramme/${d.hash}`, { fehler: String(e.message || e).slice(0, 500) }).catch(() => {});
    }
    document.querySelectorAll(`[id^="dg-${d.hash}"], [id^="ddg-${d.hash}"]`).forEach(el => el.remove());  // Mermaid-Reste
    n++;
  }
  await api('POST', `/projekte/${slug}/neu_bauen`);
  return n;
}

/* ---------------- Tab: Vorschau ---------------- */
const ST_ICON = { ok: '<span title="geprüft" style="color:var(--ok)">✓</span>', fehler: '<span title="Fehler" style="color:var(--err)">⚠</span>',
  nicht_pruefbar: '<span title="ungeprüft" style="color:var(--warn)">⚠</span>', ungeprueft: '' };

function kurztext(el) {
  const t = el.titel || el.begriff || el.md || el.tex || el.vorne_md || el.frage_md || el.alt || el.wort || el.befehl || el.name || el.ort ||
    el.gleichung || el.aufgabe_md || el.anweisung_md || el.text || el.mermaid || el.start || (el.kopf || []).join(' | ') || '';
  return String(t).replace(/\\[()[\]]/g, '').replace(/\s+/g, ' ').slice(0, 90);
}

async function tabVorschau(p, ziel) {
  if (!p.hat_seite) { ziel.innerHTML = `<p class="leer">Noch keine Seite. <a href="#/p/${p.slug}/generieren">Generieren</a></p>`; return; }
  const doc = await api('GET', `/projekte/${p.slug}/inhalt`);
  ziel.innerHTML = `<div class="reihe ende vs-kopf"><button class="btn klein" id="ergBtn" type="button" title="Fehlende Themen oder Inhalte nachgenerieren lassen">Ergänzen …</button><a class="btn primary klein" href="/api/projekte/${p.slug}/seite" target="_blank" rel="noopener">Zum Üben im ganzen Fenster öffnen ↗</a></div>
  <div class="vs">
    <iframe id="ifr" src="/api/projekte/${p.slug}/seite?vorschau=1&t=${Date.now()}" title="Vorschau der Lernseite"></iframe>
    <div class="seitenleiste">
      <div class="tabs"><button aria-pressed="true" data-t="baum">Elemente</button><button aria-pressed="false" data-t="json">JSON</button></div>
      <div class="baum" id="baum"></div>
      <div id="jsonBox" hidden style="display:flex;flex-direction:column;gap:8px;flex:1;min-height:0">
        <textarea class="json-ed" id="json" spellcheck="false" aria-label="inhalt.json"></textarea>
        <ul class="fehlerliste" id="jsonFehler"></ul>
        <div class="reihe"><button class="btn primary" id="jsonSpeichern">Speichern, prüfen &amp; bauen</button><span class="muted klein">Geänderte Elemente werden gesperrt.</span></div>
      </div>
      <div class="log" id="log" hidden></div>
    </div></div>`;
  const ifr = $('#ifr');
  $('#ergBtn').onclick = () => {
    const d = $('#dlg'), f = $('#dlgForm');
    f.innerHTML = `<h2>Ergänzen</h2><p class="muted">Was fehlt auf der Seite? Die KI liefert nur Neues aus deinen Unterlagen – Bestehendes bleibt unverändert.</p>
      <label class="feld">Was fehlt?<textarea name="hinweis" rows="3" required placeholder="z. B. „Das Thema Normalformen fehlt“ oder „mehr Übungsaufgaben zu JOINs“"></textarea></label>
      <div class="reihe ende"><button class="btn" value="nein" formnovalidate>Abbrechen</button><button class="btn primary" value="ja">Ergänzen</button></div>`;
    d.returnValue = '';
    d.onclose = async () => {
      if (d.returnValue !== 'ja') return;
      const hinweis = String(new FormData(f).get('hinweis') || '').trim();
      if (!hinweis) return;
      const log = $('#log'); log.hidden = false; $('#ergBtn').disabled = true;
      try {
        const e = await jobStarten(p.slug, { art: 'ergaenzen', hinweis }, log);
        toast(e.typ === 'fertig' ? 'Ergänzt' : e.text, e.typ !== 'fertig');
        if (e.typ === 'fertig') route();
      } catch (err) { toast(err.message, true); }
      $('#ergBtn').disabled = false;
    };
    d.showModal();
  };
  diagrammeZeichnen(p.slug, (t) => toast(t)).then(n => {
    if (n) { toast(`${n} Diagramm(e) gezeichnet`); ifr.src = `/api/projekte/${p.slug}/seite?vorschau=1&t=${Date.now()}`; }
  });
  const zeige = (id) => { try { ifr.contentWindow.postMessage({ genutZeige: id }, '*'); } catch (e) { /* ignorieren */ } };
  const knoten = (el, typ) => `
    <div class="knoten" data-id="${esc(el.id)}">
      <div class="zeile"><span class="typ">${esc(typ)}</span><span class="txt">${esc(kurztext(el))}</span>
        ${el.quelle === 'ki' ? '<span class="chip">KI</span>' : ''}${el.gesperrt ? '<span title="gesperrt">🔒</span>' : ''}<span class="st">${ST_ICON[el.pruefung && el.pruefung.status] || ''}</span></div>
      <div class="aktionen">
        ${el.pruefung && el.pruefung.meldungen.length ? `<div class="meld">${el.pruefung.meldungen.map(esc).join('<br>')}</div>` : ''}
        <input type="text" placeholder="Hinweis, z. B. „einfacher erklären“" aria-label="Hinweis für die KI">
        <button class="btn klein" data-neu>Neu generieren</button><button class="btn klein gefahr" data-loesch>Löschen</button>
      </div>
    </div>`;
  const themen = doc.themen.map(t => `
    <div class="knoten thema-kn" data-id="${esc(t.id)}"><div class="zeile"><span class="typ">thema</span><span class="txt">${esc(t.titel)}</span></div>
      <div class="aktionen"><button class="btn klein gefahr" data-loesch>Thema samt Aufgaben, Karten &amp; Quiz löschen</button></div></div>
    ${t.bloecke.map(b => knoten(b, b.typ)).join('')}`).join('');
  $('#baum').innerHTML = `<h4>Themen</h4>${themen || '<p class="leer">–</p>'}
    <h4>Aufgaben</h4>${doc.aufgaben.map(a => knoten(a, a.art === 'probe' ? 'probe' : 'aufgabe')).join('') || '<p class="leer">–</p>'}
    <h4>Karten</h4>${doc.karten.map(k => knoten(k, 'karte')).join('') || '<p class="leer">–</p>'}
    <h4>Quiz</h4>${(doc.quiz || []).map(q => knoten(q, q.art === 'mc' ? 'quiz' : 'w/f')).join('') || '<p class="leer">–</p>'}`;
  $$('#baum .knoten').forEach(k => {
    $('.zeile', k).onclick = () => { $$('#baum .knoten.offen').forEach(o => { if (o !== k) o.classList.remove('offen'); }); k.classList.toggle('offen'); zeige(k.dataset.id); };
    const del = $('[data-loesch]', k);
    if (del) del.onclick = async () => {
      if (!await frage('Element löschen?', `<p>${esc(kurztext({ titel: $('.txt', k).textContent }))}</p>`, 'Löschen', true)) return;
      try { await api('DELETE', `/projekte/${p.slug}/elemente/${k.dataset.id}`); toast('Gelöscht'); route(); } catch (e) { toast(e.message, true); }
    };
    const neu = $('[data-neu]', k);
    if (neu) neu.onclick = async () => {
      neu.disabled = true;
      try {
        const e = await jobStarten(p.slug, { art: 'block_neu', id: k.dataset.id, hinweis: $('input', k).value }, $('#log'));
        toast(e.typ === 'fertig' ? 'Neu generiert' : e.text, e.typ !== 'fertig'); if (e.typ === 'fertig') route(); else neu.disabled = false;
      } catch (err) { toast(err.message, true); neu.disabled = false; }
    };
  });
  // JSON-Editor
  $('#json').value = JSON.stringify(doc, null, 2);
  $$('.tabs button').forEach(b => b.onclick = () => {
    $$('.tabs button').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
    $('#baum').hidden = b.dataset.t !== 'baum'; $('#jsonBox').hidden = b.dataset.t !== 'json';
  });
  $('#jsonSpeichern').onclick = async () => {
    $('#jsonFehler').innerHTML = '';
    try {
      const r = await api('PUT', `/projekte/${p.slug}/inhalt`, $('#json').value, true);
      toast(`Gespeichert · ${r.geaendert.length} Element(e) geändert`); route();
    } catch (e) {
      const liste = (e.detail && e.detail.fehler) || [e.message];
      $('#jsonFehler').innerHTML = liste.map(f => `<li>${esc(f)}</li>`).join('');
    }
  };
}

/* ---------------- Tab: Export ---------------- */
async function tabExport(p, ziel) {
  const info = (await kiLaden()).pages ? await api('GET', `/projekte/${p.slug}/pages`) : null;
  ziel.innerHTML = `<div class="eng raster">
    <div class="karte"><h2>Herunterladen</h2><p>Eine einzige HTML-Datei, funktioniert offline – per WhatsApp, Mail oder USB-Stick teilbar.</p>
      ${p.hat_seite ? `<a class="btn primary" href="/api/projekte/${p.slug}/download">${esc(p.slug)}.html herunterladen</a>` : '<p class="leer">Noch keine Seite gebaut.</p>'}</div>
    ${info ? `<div class="karte"><h2>Auf GitHub Pages veröffentlichen</h2>
      ${info.ok ? `<p>Ziel: <code>${esc(info.repo)}</code> → <a href="${esc(info.url)}" target="_blank" rel="noopener">${esc(info.url)}</a></p>
        ${info.status.veroeffentlicht ? `<p><span class="chip ok">online</span> zuletzt ${new Date(info.status.zuletzt).toLocaleString('de-AT')}</p>` : ''}
        <button class="btn primary" id="pub" ${p.hat_seite ? '' : 'disabled'}>Veröffentlichen …</button>`
      : `<p class="muted">${esc(info.fehler)}</p><p class="klein">Einrichtung: öffentliches Repo <code>lernseiten</code> anlegen, lokal klonen, GitHub Pages auf Branch <code>main</code> / Ordner <code>/</code> aktivieren und <code>repo_pfad</code> sowie <code>basis_url</code> in <code>config.toml</code> eintragen. Danach Server neu starten.</p>`}
      <div id="pubErg"></div></div>` : ''}</div>`;
  const pub = $('#pub');
  if (pub) pub.onclick = async () => {
    const ok = await frage('Wirklich veröffentlichen?', `<p>Die Seite wird öffentlich unter<br><a href="${esc(info.url)}">${esc(info.url)}</a> erreichbar sein.</p>
      <p>Geänderte Dateien im Repo <code>${esc(info.repo)}</code>:</p><ul>${info.dateien.map(d => `<li><code>${esc(d)}</code></li>`).join('')}</ul>
      <p class="muted klein">Es wird committet und gepusht (ohne --force).</p>`, 'Ja, veröffentlichen');
    if (!ok) return;
    pub.disabled = true;
    try { const r = await api('POST', `/projekte/${p.slug}/pages`, { bestaetigt: true }); $('#pubErg').innerHTML = `<p><span class="chip ok">veröffentlicht</span> <a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.url)}</a></p>`; }
    catch (e) { toast(e.message, true); pub.disabled = false; }
  };
}

/* ---------------- Einstellungen ---------------- */
async function seiteEinstellungen() {
  const { config, pfad } = await api('GET', '/einstellungen');
  const zeile = (k, v) => `<tr><td><code>${esc(k)}</code></td><td>${esc(v === '' ? '(leer)' : v)}</td></tr>`;
  app.innerHTML = `<div class="eng"><h1>Einstellungen</h1>
    <p class="muted">Diese Werte stehen in <code>${esc(pfad)}</code>. Zum Ändern die Datei bearbeiten und den Server neu starten. Der Gemini-Schlüssel steht in der Datei <code>.env</code> (<code>GEMINI_API_KEY=…</code>) und wird hier nicht angezeigt.</p>
    ${Object.entries(config).map(([abschnitt, werte]) => `<div class="karte abstand"><h3>[${esc(abschnitt)}]</h3>
      <table style="width:100%;font-size:.9rem">${Object.entries(werte).map(([k, v]) => zeile(k, v)).join('')}</table>
      ${['claude_code', 'gemini', 'ollama'].includes(abschnitt) ? `<div class="reihe abstand"><button class="btn klein" data-test="${abschnitt}">Verbindung testen</button><span class="muted klein" data-erg="${abschnitt}"></span></div>` : ''}
    </div>`).join('')}</div>`;
  $$('[data-test]').forEach(b => b.onclick = async () => {
    const erg = $(`[data-erg="${b.dataset.test}"]`);
    b.disabled = true; erg.textContent = 'teste …';
    try { const r = await api('POST', `/modelle/${b.dataset.test}/test`); erg.textContent = r.ok ? `✓ Antwort: ${r.antwort}` : `✗ ${r.fehler}`; }
    catch (e) { erg.textContent = '✗ ' + e.message; }
    b.disabled = false;
  });
}

route();
