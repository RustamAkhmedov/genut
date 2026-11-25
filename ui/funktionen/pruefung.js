// Mündliche Prüfung (Feature 005). Wird von ui/app.js als Modul geladen: export function start(hooks).
// Schritt „Prüfung“ im Projekt: Start (US1), Chat, Ergebnis. Erweiterungen (Mikrofon T012, Verlauf T015) hängen
// sich an die Funktionen `mikrofonLeiste` und `verlaufBereich` (derzeit leer).
let H = null;
const esc = (s) => H.esc(s);

const MIN_FRAGEN = 3, MAX_FRAGEN = 12, STANDARD_FRAGEN = 6, MAX_ZEICHEN = 4000;
const pfad = (slug, rest = '') => `/projekte/${encodeURIComponent(slug)}/pruefungen${rest}`;

/** Ungefähre Zahl der Claude-Aufrufe (SC-005): Plan + n Fragen (+ bis zu n Nachfragen) + Bewertung. */
const aufrufe = (n) => [n + 2, 2 * n + 2];

/* ---------------- Erweiterungspunkte ---------------- */
/** T012: Mikrofonknopf neben „Absenden“ (Web Speech API). `leiste` ist .pr-aktionen-zusatz, `feld` das Antwortfeld.
 *  Ohne Browserunterstützung bleibt die Leiste leer. Der erkannte Text wird nur angehängt, nie gesendet. */
const MIKRO_FEHLER = {
  'not-allowed': 'Der Zugriff auf das Mikrofon ist nicht erlaubt. Erlaube ihn in den Browser-Einstellungen oder tippe deine Antwort.',
  'service-not-allowed': 'Der Zugriff auf das Mikrofon ist nicht erlaubt. Erlaube ihn in den Browser-Einstellungen oder tippe deine Antwort.',
  'no-speech': 'Ich habe nichts gehört. Versuche es noch einmal oder tippe deine Antwort.',
  'audio-capture': 'Es wurde kein Mikrofon gefunden. Tippe deine Antwort.',
  network: 'Die Spracherkennung braucht eine Internetverbindung und ist gerade nicht erreichbar. Tippe deine Antwort.',
};
const mikroGemerkt = () => { try { return localStorage.getItem('genut.mikrofon_ok') === '1'; } catch (e) { return false; } };
const mikroMerken = () => { try { localStorage.setItem('genut.mikrofon_ok', '1'); } catch (e) { /* egal */ } };
const spracheVon = (code) => {
  const c = String(code || '').toLowerCase().split(/[-_]/)[0];
  if (c === 'de') return 'de-AT';
  if (c === 'en') return 'en-GB';
  return (typeof navigator !== 'undefined' && navigator.language) || 'de-AT';
};

function mikrofonLeiste(leiste, feld, p) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR || !leiste) return;
  leiste.innerHTML = `<button class="btn pr-mikro" type="button" id="prMikro" aria-pressed="false" aria-label="Antwort sprechen">
    <span aria-hidden="true">🎤</span> <span class="pr-mikro-text">Sprechen</span></button>
    <span class="pr-mikro-status muted klein" id="prMikroStatus" role="status" aria-live="polite"></span>`;
  const knopf = leiste.querySelector('#prMikro'), status = leiste.querySelector('#prMikroStatus');
  const text = knopf.querySelector('.pr-mikro-text');
  let rec = null, basis = '', sprache = null;
  const zustand = (an) => {
    knopf.setAttribute('aria-pressed', String(an));
    knopf.classList.toggle('hoert', an);
    text.textContent = an ? 'Hört zu … (Stopp)' : 'Sprechen';
    if (an) status.textContent = 'Hört zu …';
    else if (status.textContent === 'Hört zu …') status.textContent = '';
  };
  const stopp = () => { if (rec) { try { rec.stop(); } catch (e) { /* schon beendet */ } } };
  const setzeText = (t) => {
    feld.value = (basis && t ? `${basis} ${t}` : basis + t).slice(0, feld.maxLength > 0 ? feld.maxLength : undefined);
    feld.dispatchEvent(new Event('input', { bubbles: true }));
  };
  const lang = async () => {
    if (sprache) return sprache;
    let code = null;
    try { code = (await H.api('GET', `/projekte/${encodeURIComponent(p.slug)}/inhalt`)).projekt.sprache; } catch (e) { /* Standard */ }
    return (sprache = spracheVon(code));
  };
  const los = async () => {
    status.textContent = '';
    basis = feld.value.replace(/\s+$/, '');
    rec = new SR();
    rec.lang = await lang();
    rec.interimResults = true; rec.continuous = false;
    let fehler = false;
    rec.onresult = (ev) => {
      // Immer alle Ergebnisse dieser Sitzung neu zusammensetzen (endgültige und vorläufige).
      const teile = [];
      for (let i = 0; i < ev.results.length; i++) teile.push(ev.results[i][0].transcript.trim());
      setzeText(teile.filter(Boolean).join(' '));
    };
    rec.onerror = (ev) => {
      fehler = true;
      if (ev.error === 'aborted') { fehler = false; return; }
      status.textContent = MIKRO_FEHLER[ev.error] || `Die Spracherkennung ist fehlgeschlagen (${ev.error}). Tippe deine Antwort.`;
    };
    rec.onend = () => { rec = null; zustand(false); if (!fehler) status.textContent = ''; feld.focus(); };
    try { rec.start(); zustand(true); }
    catch (e) { rec = null; zustand(false); status.textContent = 'Das Mikrofon konnte nicht gestartet werden. Tippe deine Antwort.'; }
  };
  knopf.onclick = async () => {
    if (rec) { stopp(); return; }
    if (!mikroGemerkt()) {
      const ok = await H.frage('Mikrofon verwenden?',
        '<p>Zum Erkennen der Sprache sendet dein Browser die Aufnahme möglicherweise an einen Dienst von Google oder Microsoft. Dein Text kann vor dem Absenden bearbeitet werden, gesendet wird nie automatisch.</p>', 'Verstanden');
      if (!ok) return;
      mikroMerken();
    }
    await los();
  };
}
/** T015: Liste früherer Prüfungen unter dem Startformular. Gibt HTML zurück, `bindeVerlauf` hängt Ereignisse an. */
const STATUS = { laeuft: 'läuft', abgeschlossen: 'abgeschlossen', verkuerzt: 'vorzeitig beendet' };
const datum = (iso) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? String(iso || '') : d.toLocaleString('de-AT', { dateStyle: 'medium', timeStyle: 'short' });
};
function verlaufBereich(liste) {
  if (!liste || !liste.length) return '';
  return `<section class="pr-liste-box" aria-labelledby="prListeTitel"><h2 id="prListeTitel">Frühere Prüfungen</h2>
    <ul class="pr-liste">${liste.map((e) => `<li class="pr-eintrag" data-id="${esc(e.id)}">
      <div class="pr-eintrag-kopf"><span class="pr-datum">${esc(datum(e.erstellt))}</span>
        <span class="chip ${e.note ? '' : 'warn'}">${e.note ? `Note ${esc(e.note)}${e.note_name ? ' · ' + esc(e.note_name) : ''}` : esc(STATUS[e.status] || e.status)}</span></div>
      <div class="pr-eintrag-themen">${(e.themen || []).map(esc).join(', ')} <span class="muted klein">· ${esc(e.fragen)} Fragen</span></div>
      <div class="reihe"><button class="btn klein pr-oeffnen" type="button" data-id="${esc(e.id)}">Öffnen</button>
        <button class="btn klein pr-loeschen" type="button" data-id="${esc(e.id)}" data-datum="${esc(datum(e.erstellt))}">Löschen</button></div></li>`).join('')}</ul></section>`;
}
function bindeVerlauf(ziel, kontext) {
  const { p } = kontext;
  ziel.querySelectorAll('.pr-oeffnen').forEach((b) => {
    b.onclick = async () => {
      try { zeigeZustand(p, ziel, await H.api('GET', pfad(p.slug, `/${encodeURIComponent(b.dataset.id)}`))); }
      catch (e) { H.toast(e.message, true); }
    };
  });
  ziel.querySelectorAll('.pr-loeschen').forEach((b) => {
    b.onclick = async () => {
      if (!(await H.frage('Prüfung löschen?', `<p>Die Prüfung vom ${esc(b.dataset.datum)} wird samt Verlauf und Ergebnis gelöscht.</p>`, 'Löschen', true))) return;
      try { await H.api('DELETE', pfad(p.slug, `/${encodeURIComponent(b.dataset.id)}`)); await zeigeStart(p, ziel); }
      catch (e) { H.toast(e.message, true); }
    };
  });
}

/* ---------------- Start ---------------- */
async function zeigeStart(p, ziel, vorauswahl = null) {
  const [themen, liste] = await Promise.all([
    H.api('GET', `/projekte/${encodeURIComponent(p.slug)}/themen`),
    H.api('GET', pfad(p.slug)),
  ]);
  if (liste.laufend) { await zeigeLaufende(p, ziel, liste.laufend); return; }
  if (!themen.length) {
    ziel.innerHTML = '<p class="leer">Dieses Projekt hat noch keinen Inhalt. Erzeuge zuerst eine Lernseite.</p>';
    return;
  }
  const an = (t) => (vorauswahl ? vorauswahl.includes(t.id) || vorauswahl.includes(t.titel) : true);
  ziel.innerHTML = `<div class="pr">
    <section class="karte pr-start">
      <h2>Mündliche Prüfung</h2>
      <p class="muted">Ein Prüfer stellt dir Fragen zu den gewählten Themen. Antworte in eigenen Worten, am Ende gibt es eine Note.</p>
      <form id="prForm" novalidate>
        <fieldset class="pr-themen"><legend class="eyebrow">Themen</legend>
          <div class="reihe"><button class="btn klein" type="button" id="prAlle">Alle</button><button class="btn klein" type="button" id="prKeine">Keine</button>
            <span class="muted klein" id="prZaehler" aria-live="polite"></span></div>
          <ul class="pr-themenliste">${themen.map((t, i) => `<li><label class="pr-wahl"><input type="checkbox" name="thema" value="${esc(t.id)}" ${an(t) ? 'checked' : ''}><span>${esc(t.titel)}</span></label></li>`).join('')}</ul>
        </fieldset>
        <label class="feld pr-fragen">Anzahl der Fragen (${MIN_FRAGEN} bis ${MAX_FRAGEN})
          <input type="number" id="prFragen" min="${MIN_FRAGEN}" max="${MAX_FRAGEN}" value="${STANDARD_FRAGEN}" inputmode="numeric"></label>
        <p class="pr-hinweis" id="prAufrufe" role="status"></p>
        <div class="reihe"><button class="btn primary" type="submit" id="prStart">Prüfung starten</button></div>
        <p class="pr-fehler" id="prStartFehler" role="alert" hidden></p>
      </form>
    </section>
    ${verlaufBereich(liste.liste)}</div>`;
  const q = (s) => ziel.querySelector(s), boxen = () => Array.from(ziel.querySelectorAll('input[name=thema]'));
  const fragen = () => {
    const n = Number(q('#prFragen').value);
    return Number.isInteger(n) && n >= MIN_FRAGEN && n <= MAX_FRAGEN ? n : null;
  };
  const aktualisieren = () => {
    const n = fragen(), g = boxen().filter((c) => c.checked).length;
    q('#prZaehler').textContent = `${g} von ${themen.length} gewählt`;
    if (n === null) q('#prAufrufe').textContent = `Bitte eine Zahl von ${MIN_FRAGEN} bis ${MAX_FRAGEN} eingeben.`;
    else { const [a, b] = aufrufe(n); q('#prAufrufe').textContent = `Das braucht ca. ${a} bis ${b} Claude-Aufrufe aus deinem Abo.`; }
    q('#prStart').disabled = n === null || !g;
  };
  q('#prAlle').onclick = () => { boxen().forEach((c) => { c.checked = true; }); aktualisieren(); };
  q('#prKeine').onclick = () => { boxen().forEach((c) => { c.checked = false; }); aktualisieren(); };
  q('#prForm').onchange = aktualisieren;
  q('#prFragen').oninput = aktualisieren;
  q('#prForm').onsubmit = async (ev) => {
    ev.preventDefault();
    const n = fragen(), gewaehlt = boxen().filter((c) => c.checked).map((c) => c.value);
    if (n === null || !gewaehlt.length) return;
    const knopf = q('#prStart'), fehler = q('#prStartFehler');
    knopf.disabled = true; fehler.hidden = true;
    q('#prAufrufe').textContent = 'Prüfer bereitet die Fragen vor …';
    try {
      zeigeChat(p, ziel, await H.api('POST', pfad(p.slug), { themen: gewaehlt, fragen: n }));
    } catch (e) {
      fehler.textContent = e.message; fehler.hidden = false;
      aktualisieren();
    }
  };
  bindeVerlauf(ziel, { p, ziel, themen, neuStarten: (ids) => zeigeStart(p, ziel, ids) });
  aktualisieren();
}

async function zeigeLaufende(p, ziel, id) {
  zeigeZustand(p, ziel, await H.api('GET', pfad(p.slug, `/${encodeURIComponent(id)}`)));
}

function zeigeZustand(p, ziel, z) {
  if (z.ergebnis || z.status !== 'laeuft') zeigeErgebnis(p, ziel, z);
  else zeigeChat(p, ziel, z);
}

/* ---------------- Chat ---------------- */
const blase = (n) => `<div class="pr-zeile ${n.art === 'pruefer' ? 'pruefer' : 'schueler'}">
  <div class="pr-blase"><span class="pr-wer">${n.art === 'pruefer' ? (n.typ === 'nachfrage' ? 'Prüfer · Nachfrage' : 'Prüfer') : 'Du'}</span>
  <div class="pr-text">${esc(n.text || '(keine Antwort)')}</div></div></div>`;

function zeigeChat(p, ziel, z, opt = {}) {
  const id = encodeURIComponent(z.id);
  const nr = z.aktuelle_frage || 1;
  ziel.innerHTML = `<div class="pr pr-chat">
    <div class="pr-kopf"><h2 id="prFrageNr">Frage ${esc(nr)} von ${esc(z.fragen_anzahl)}</h2>
      <button class="btn" type="button" id="prBeenden">Prüfung beenden</button></div>
    ${z.hinweis ? `<p class="pr-hinweis">${esc(z.hinweis)}</p>` : ''}
    <div class="pr-verlauf" id="prVerlauf" role="log" aria-live="polite" aria-label="Gespräch mit dem Prüfer">${z.verlauf.map(blase).join('')}
      <div class="pr-denkt" id="prDenkt" hidden>Prüfer denkt …</div></div>
    <p class="pr-fehler" id="prFehler" role="alert" hidden></p>
    <div class="pr-eingabe" id="prEingabe">
      <label class="feld" for="prAntwort">Deine Antwort <span class="hilfe">Strg+Enter sendet</span></label>
      <textarea id="prAntwort" rows="4" maxlength="${MAX_ZEICHEN}" placeholder="Antworte in eigenen Worten …"></textarea>
      <div class="reihe pr-aktionen"><span class="pr-aktionen-zusatz"></span>
        <span class="muted klein pr-zaehler" id="prZeichen"></span>
        <button class="btn primary" type="button" id="prSenden">Absenden</button></div>
    </div></div>`;
  const q = (s) => ziel.querySelector(s);
  const feld = q('#prAntwort'), senden = q('#prSenden'), fehler = q('#prFehler'), denkt = q('#prDenkt'), verlauf = q('#prVerlauf');
  const runter = () => { verlauf.scrollTop = verlauf.scrollHeight; denkt.scrollIntoView({ block: 'nearest' }); };
  const beschaeftigt = (an) => {
    feld.disabled = an; senden.disabled = an; q('#prBeenden').disabled = an; denkt.hidden = !an;
    q('#prEingabe').setAttribute('aria-busy', String(an));
    if (an) runter();
  };
  const zaehler = () => { q('#prZeichen').textContent = feld.value.length > MAX_ZEICHEN * 0.8 ? `${feld.value.length} / ${MAX_ZEICHEN}` : ''; };
  const zeigeFehler = (text, weiter) => {
    fehler.innerHTML = `<span>${esc(text)}</span>${weiter ? ' <button class="btn" type="button" id="prWeiter">Weiter versuchen</button>' : ''}`;
    fehler.hidden = false;
    if (weiter) q('#prWeiter').onclick = weiterVersuchen;
  };
  const uebernehmen = (neu) => { zeigeZustand(p, ziel, neu); const f = ziel.querySelector('#prAntwort'); if (f) f.focus(); };
  /** Nach einem Fehler beim Senden: Hat der Server die Antwort gespeichert (wartet), gibt es „Weiter versuchen“. */
  const nachFehler = async (e) => {
    beschaeftigt(false);
    try {
      const neu = await H.api('GET', pfad(p.slug, `/${id}`));
      if (neu.wartet) { zeigeChat(p, ziel, neu, { fehler: e.message }); return; }
    } catch (e2) { /* Meldung unten */ }
    zeigeFehler(e.message, false);
  };
  async function weiterVersuchen() {
    fehler.hidden = true; beschaeftigt(true);
    try { uebernehmen(await H.api('POST', pfad(p.slug, `/${id}/weiter`))); } catch (e) { await nachFehler(e); }
  }
  const absenden = async () => {
    const text = feld.value.trim();
    if (feld.value.length > MAX_ZEICHEN) { zeigeFehler(`Die Antwort ist zu lang (höchstens ${MAX_ZEICHEN} Zeichen).`, false); return; }
    if (!text && !(await H.frage('Ohne Antwort weiter?', '<p>Die Frage zählt als „nicht beantwortet“ und bringt keine Punkte.</p>', 'Weiter'))) return;
    fehler.hidden = true;
    verlauf.insertBefore(Object.assign(document.createElement('div'), { innerHTML: blase({ art: 'schueler', text }) }).firstElementChild, denkt);
    beschaeftigt(true);
    try { uebernehmen(await H.api('POST', pfad(p.slug, `/${id}/antwort`), { text })); }
    catch (e) { await nachFehler(e); }
  };
  senden.onclick = absenden;
  feld.onkeydown = (ev) => { if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); absenden(); } };
  feld.oninput = zaehler;
  q('#prBeenden').onclick = async () => {
    if (!(await H.frage('Prüfung beenden?', '<p>Die Prüfung wird mit den bisherigen Antworten bewertet. Offene Fragen zählen nicht.</p>', 'Beenden', true))) return;
    fehler.hidden = true; beschaeftigt(true);
    try { zeigeZustand(p, ziel, await H.api('POST', pfad(p.slug, `/${id}/beenden`))); }
    catch (e) { beschaeftigt(false); zeigeFehler(e.message, false); }
  };
  mikrofonLeiste(q('.pr-aktionen-zusatz'), feld, p);

  if (z.wartet) {
    // Antwort ist gespeichert, der Zug fehlt noch: Eingabe sperren, bis es weitergeht.
    feld.disabled = true; senden.disabled = true;
    zeigeFehler(opt.fehler || 'Der Prüfer hat noch nicht geantwortet. Deine Antwort ist gespeichert.', true);
  } else if (!opt.ohneFokus) feld.focus();
  verlauf.scrollTop = verlauf.scrollHeight;
}

/* ---------------- Ergebnis ---------------- */
function zeigeErgebnis(p, ziel, z) {
  const e = z.ergebnis;
  if (!e) { ziel.innerHTML = '<p class="leer">Diese Prüfung hat kein Ergebnis.</p>'; return; }
  const note = e.note;
  ziel.innerHTML = `<div class="pr pr-ergebnis">
    <section class="karte pr-note-box note-${note || 'x'}" aria-labelledby="prNoteTitel">
      <div class="eyebrow" id="prNoteTitel">Ergebnis</div>
      <div class="pr-note" aria-label="Note ${esc(note ?? 'keine')}">${esc(note ?? '–')}</div>
      <div class="pr-note-name">${esc(e.note_name || 'Keine Note')}</div>
      <div class="pr-punkte">${esc(e.punkte)} von ${esc(e.maximal)} Punkten · ${esc(Math.round(e.prozent))} %</div>
      ${e.verkuerzt ? '<span class="chip warn">vorzeitig beendet</span>' : ''}
    </section>
    ${z.hinweis ? `<p class="pr-hinweis">${esc(z.hinweis)}</p>` : ''}
    ${e.begruendung ? `<section class="pr-abschnitt"><h2>Begründung</h2><p class="pr-begruendung">${esc(e.begruendung)}</p></section>` : ''}
    ${e.luecken && e.luecken.length ? `<section class="pr-abschnitt"><h2>Lücken</h2><ul class="pr-luecken">${e.luecken.map((l) => `<li class="pr-luecke">
      ${l.link ? `<a class="pr-link" href="${esc(l.link)}">${esc(l.titel || l.thema_id)}</a>` : `<strong>${esc(l.titel || l.thema_id)}</strong>`}
      <div>${esc(l.hinweis)}</div></li>`).join('')}</ul></section>` : ''}
    ${e.rueckmeldungen && e.rueckmeldungen.length ? `<section class="pr-abschnitt"><h2>Rückmeldung je Frage</h2><ul class="pr-rueck">${e.rueckmeldungen.map((r) => {
      const frage = (z.verlauf || []).find((n) => n.art === 'pruefer' && n.nr === r.nr && n.typ === 'frage');
      return `<li class="pr-rueck-eintrag"><div class="pr-rueck-kopf"><strong>Frage ${esc(r.nr)}</strong><span class="chip ${r.punkte === 2 ? 'ok' : r.punkte === 1 ? 'warn' : 'err'}">${esc(r.punkte)} von 2 Punkten</span></div>
        ${frage ? `<div class="muted klein">${esc(frage.text)}</div>` : ''}
        ${r.fehlte ? `<div><span class="pr-label">Es fehlte:</span> ${esc(r.fehlte)}</div>` : ''}
        ${r.stoff_hinweis ? `<div><span class="pr-label">Nachlesen:</span> ${esc(r.stoff_hinweis)}</div>` : ''}</li>`;
    }).join('')}</ul></section>` : ''}
    ${z.verlauf && z.verlauf.length ? `<details class="pr-gespraech"><summary>Gespräch anzeigen</summary><div class="pr-verlauf pr-verlauf-statisch">${z.verlauf.map(blase).join('')}</div></details>` : ''}
    <div class="reihe pr-ende"><button class="btn primary" type="button" id="prNochmal">Nochmal mit denselben Themen</button>
      <button class="btn" type="button" id="prListe">Zur Liste</button></div></div>`;
  ziel.querySelector('#prListe').onclick = () => zeigeStart(p, ziel).catch((e) => H.toast(e.message, true));
  ziel.querySelector('#prNochmal').onclick = async (ev) => {
    const knopf = ev.currentTarget;
    knopf.disabled = true;
    try {
      const da = new Set((await H.api('GET', `/projekte/${encodeURIComponent(p.slug)}/themen`)).map((t) => t.id));
      const ids = (z.themen || []).filter((i) => da.has(i));
      if (!ids.length) throw new Error('Die Themen dieser Prüfung gibt es nicht mehr. Wähle neue Themen.');
      if (ids.length < (z.themen || []).length) H.toast('Gelöschte Themen wurden weggelassen.');
      zeigeChat(p, ziel, await H.api('POST', pfad(p.slug), { themen: ids, fragen: z.fragen_gewuenscht || STANDARD_FRAGEN }));
    } catch (e) { knopf.disabled = false; H.toast(e.message, true); }
  };
}

/* ---------------- Verfügbarkeit ---------------- */
// Bei `pruefung = "auto"` gibt es die Prüfung nur, solange Claude bereit ist. Das kann sich ohne Neustart ändern.
let verfuegbar = false, abfrage = null;
function verfuegbarAbfragen() {
  abfrage = abfrage || H.api('GET', '/pruefung/verfuegbar').then((r) => r.verfuegbar === true, () => false)
    .then((v) => { verfuegbar = v; abfrage = null; return v; });
  return abfrage;
}

/** Zeigt den zuletzt bekannten Stand und fragt neu ab; hat er sich geändert, wird die Seite neu gezeichnet. */
function sichtbar(p) {
  if (!(p.zahlen && p.zahlen.themen > 0)) return false;
  const gezeigt = verfuegbar, hash = location.hash;
  verfuegbarAbfragen().then((v) => {
    if (v !== gezeigt && location.hash === hash) window.dispatchEvent(new HashChangeEvent('hashchange'));
  });
  return gezeigt;
}

/* ---------------- Start des Moduls ---------------- */
async function tabPruefung(p, ziel) {
  if (!(await verfuegbarAbfragen())) {
    ziel.innerHTML = '<p class="leer">Die mündliche Prüfung gibt es nur, wenn Claude Code bereit ist.</p>';
    return;
  }
  try { await zeigeStart(p, ziel); }
  catch (e) { ziel.innerHTML = `<div class="karte eng"><h2>Fehler</h2><p>${esc(e.message)}</p></div>`; }
}

export async function start(hooks) {
  H = hooks;
  if (!document.querySelector('link[data-pruefung]')) {
    const l = document.createElement('link');
    l.rel = 'stylesheet'; l.href = '/ui/funktionen/pruefung.css'; l.dataset.pruefung = '1';
    document.head.appendChild(l);
  }
  H.schritt('pruefung', 'Prüfung', sichtbar, tabPruefung);
  // Kurz auf die erste Antwort warten, damit der Schritt gleich da ist; eine langsame Erkennung hält die App nicht auf.
  await Promise.race([verfuegbarAbfragen(), new Promise((fertig) => { setTimeout(fertig, 500); })]);
}
