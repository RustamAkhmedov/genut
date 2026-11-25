// KI-Einrichtung (Feature 005b). Wird von ui/app.js als Modul geladen: export function start(hooks).
// Zustände im KI-Schalter, Hinweis ohne bereite KI, Prüfung vor jedem Auftrag und der Dialog je KI.
let H = null;
const esc = (s) => H.esc(s);

const NAMEN = { claude_code: 'Claude', gemini: 'Gemini', ollama: 'Lokal' };
const KLASSE = { bereit: 'ki-bereit', nicht_eingerichtet: 'ki-fehlt', problem: 'ki-problem' };
const SYMBOL = { nicht_eingerichtet: '＋', problem: '⚠' };
const WORT = { bereit: 'bereit', nicht_eingerichtet: 'nicht eingerichtet', problem: 'Problem' };
const OHNE_KI = ['pruefen_bauen']; // diese Aufträge brauchen keine KI

/* ---------------- Zustände ---------------- */
let stand = null;      // letzte Antwort von /ki/zustaende: {zustaende, keine_bereit}
let knoepfe = {};      // Knöpfe der letzten Zeichnung des Schalters
let hinweisEl = null;  // Stelle „kopf-hinweis“
let laufend = null;    // laufende Abfrage ohne neu=1
let nummer = 0, uebernommen = 0;

const zustandVon = (name) => (stand ? stand.zustaende.find((z) => z.name === name) : undefined);

/** Holt die Zustände, zeichnet Schalter und Hinweis nach und liefert den neuesten Stand (null: noch keiner).
 *  Scheitert die Abfrage, bleibt der letzte Stand; mit `streng` wird der Fehler weitergereicht. */
function laden(neu = false, streng = false) {
  if (!neu && !streng && laufend) return laufend;
  const meine = ++nummer;
  const p = H.api('GET', `/ki/zustaende?neu=${neu ? 1 : 0}`).then((antwort) => {
    if (meine > uebernommen) { uebernommen = meine; stand = antwort; anwenden(); } // spät eintreffende alte Antworten verwerfen
    return stand;
  }, (e) => { if (streng) throw e; return stand; })
    .finally(() => { if (laufend === p) laufend = null; });
  if (!neu) laufend = p;
  return p;
}

function anwenden() {
  for (const [name, knopf] of Object.entries(knoepfe)) knopfZeichnen(name, knopf);
  hinweisZeichnen();
}

/* ---------------- Schalter ---------------- */
function span(klasse, text) {
  const s = document.createElement('span');
  s.className = klasse; s.textContent = text; s.setAttribute('aria-hidden', 'true');
  return s;
}

function beschreibung(z) {
  const name = NAMEN[z.name] + (z.name === 'ollama' ? ' (experimentell)' : '');
  return `${name}: ${WORT[z.zustand]}${z.zustand !== 'bereit' && z.ursache ? `, ${z.ursache}` : ''}`;
}

function titel(z) {
  if (z.zustand === 'bereit') return `${NAMEN[z.name]} ist bereit`;
  if (z.zustand === 'problem') return `${NAMEN[z.name]}: ${z.ursache || 'Problem'}`;
  return z.ursache ? `${NAMEN[z.name]} ist nicht eingerichtet: ${z.ursache}` : `${NAMEN[z.name]} ist nicht eingerichtet. Zum Einrichten klicken.`;
}

/** Ändert nur Klasse, Inhalt und Attribute, damit der Fokus auf dem Knopf bleibt. */
function knopfZeichnen(name, knopf) {
  if (!NAMEN[name]) return;
  const z = zustandVon(name);
  knopf.classList.remove(...Object.values(KLASSE));
  const teile = [span('ki-name', NAMEN[name])];
  if (name === 'ollama') teile.push(span('ki-exp', 'experimentell'));
  if (z) {
    knopf.classList.add(KLASSE[z.zustand]);
    if (SYMBOL[z.zustand]) teile.unshift(span('ki-symbol', SYMBOL[z.zustand]));
    const laeuft = z.auftrag ? 'Einrichtung läuft' : '';
    knopf.setAttribute('aria-label', [beschreibung(z), laeuft].filter(Boolean).join(', '));
    knopf.title = [titel(z), laeuft].filter(Boolean).join('. ');
  } else {
    knopf.removeAttribute('aria-label'); knopf.removeAttribute('title');
  }
  if (z && (z.zustand !== 'bereit' || z.auftrag)) knopf.setAttribute('aria-haspopup', 'dialog');
  else knopf.removeAttribute('aria-haspopup');
  knopf.replaceChildren(...teile);
}

function schalterGezeichnet(neueKnoepfe) {
  knoepfe = neueKnoepfe;
  for (const [name, knopf] of Object.entries(knoepfe)) {
    if (!NAMEN[name]) continue;
    const umschalten = knopf.onclick;
    knopf.onclick = async () => {
      if (!stand) await laden();
      const z = zustandVon(name);
      if (z && z.zustand !== 'bereit') { einrichtenDialog(name); return; } // nur bereite KIs sind umschaltbar (FR-009)
      await umschalten.call(knopf);
      if (z && z.auftrag) einrichtenDialog(name); // bereit, aber eine Einrichtung läuft noch: Fortschritt zeigen
    };
  }
  anwenden(); // erst den letzten Stand zeigen, dann aktualisieren
  laden();
}

/* ---------------- Hinweis ohne bereite KI ---------------- */
function hinweisZeichnen() {
  if (!hinweisEl) return;
  if (!(stand && stand.keine_bereit)) { hinweisEl.replaceChildren(); return; }
  if (hinweisEl.firstElementChild) return; // steht schon da (Fokus bleibt)
  const box = document.createElement('div');
  box.className = 'ki-hinweis'; box.setAttribute('role', 'status');
  box.innerHTML = `<span class="ki-hinweis-symbol" aria-hidden="true">⚠</span>
    <p><strong>Richte zuerst eine KI ein.</strong> Wähle oben im KI-Schalter eine KI mit ＋ oder ⚠. Bis dahin kann nichts erzeugt werden; Ansehen und Exportieren gehen weiter.</p>
    <button type="button" class="btn klein">Zum KI-Schalter</button>`;
  box.querySelector('button').onclick = () => {
    const schalter = document.querySelector('.ki-schalter');
    const ziel = schalter.hidden ? null : schalter.querySelector('[data-ki]');
    if (ziel) ziel.focus();
    else if (stand.zustaende.length) einrichtenDialog(stand.zustaende[0].name); // Schalter versteckt (nur eine KI)
  };
  hinweisEl.replaceChildren(box);
}

/* ---------------- Dialoge ---------------- */
// Eigenes Element statt #dlg: Aufträge starten teils aus dessen onclose, und die Einrichtung läuft länger.
let dlg = null;
let dlgKi = null; // KI des Dialogs „einrichten“: dorthin gehört der Fokus nach dem Schließen
let offen = 0; // zählt die gezeigten Inhalte; späte Antworten für ältere werden ignoriert

/** Öffnet den Dialog (oder ersetzt seinen Inhalt). aktionen: [{text, klick, primaer}], „Schließen“ kommt dazu. */
function dialogZeigen(ueberschrift, aktionen, schliessen = 'Schließen') {
  if (!dlg) {
    dlg = document.createElement('dialog');
    dlg.className = 'ki-dlg'; dlg.setAttribute('aria-labelledby', 'kiDlgTitel');
    dlg.addEventListener('close', () => {
      if (dlg.open) return;
      offen++;
      // Wurde der Schalter bei offenem Dialog neu gezeichnet, gibt es den Ausgangsknopf nicht mehr.
      const f = document.activeElement; // ohne Ziel steht der Fokus hier noch im Dialog oder schon auf body
      if (dlgKi && (!f || f === document.body || dlg.contains(f))) knoepfe[dlgKi]?.focus();
    });
    document.body.appendChild(dlg);
  }
  offen++;
  dlgKi = null;
  dlg.innerHTML = `<div class="ki-dlg-box"><h2 id="kiDlgTitel">${esc(ueberschrift)}</h2>
    <div class="ki-dlg-inhalt" aria-live="polite"></div>
    <div class="reihe ende ki-dlg-aktionen"></div></div>`;
  const leiste = dlg.querySelector('.ki-dlg-aktionen');
  const alle = [{ text: schliessen, klick: () => dlg.close() }, ...aktionen];
  for (const a of alle) {
    const b = document.createElement('button');
    b.type = 'button'; b.className = a.primaer ? 'btn primary' : 'btn'; b.textContent = a.text;
    b.onclick = () => a.klick(b);
    leiste.appendChild(b);
  }
  if (!dlg.open) dlg.showModal();
  (leiste.querySelector('.primary') || leiste.querySelector('button')).focus();
  return { inhalt: dlg.querySelector('.ki-dlg-inhalt'), leiste, marke: offen };
}

/* ---------------- Dialog „<KI> einrichten“ ---------------- */
// Inhalt je KI für Zustände ungleich „bereit“: EINRICHTUNG[name](element, zustand, helfer).
// `element` ist leer. helfer: pruefen() fragt mit neu=1 ab und zeichnet den Dialog neu; folgen(kennung) zeigt
// den gestarteten Auftrag; senden(knopf, pfad, body, melden) schickt eine Einrichtung ab. Nach einem
// gescheiterten Auftrag ist helfer.gescheitert wahr; helfer.wahl ist der zuletzt abgeschickte Body.
// Rückgabe true: der Inhalt hat eine eigene Hauptaktion („Erneut prüfen“ ist dann nachrangig).
const SCHLUESSEL_SEITE = 'https://aistudio.google.com/apikey';
const NOCHMAL = 'Nochmal versuchen'; // Hauptaktion nach einem gescheiterten Auftrag
const TAKT = 1000; // ms zwischen zwei Abfragen eines laufenden Auftrags

function ursacheKasten(z) {
  const text = z.ursache || (z.zustand === 'nicht_eingerichtet' ? `${NAMEN[z.name]} ist auf diesem Rechner noch nicht eingerichtet.` : 'Unbekannte Ursache');
  return `<p class="ki-ursache ${KLASSE[z.zustand]}"><span aria-hidden="true">${SYMBOL[z.zustand]}</span>
    <span><strong>${esc(z.zustand === 'problem' ? 'Problem' : 'Nicht eingerichtet')}:</strong> ${esc(text)}</span></p>`;
}

function ursacheZeichnen(element, z) {
  element.innerHTML = `${ursacheKasten(z)}
    <p class="muted klein">Wenn du die Ursache behoben hast, wähle „Erneut prüfen“.</p>`;
}

/** Knopf während der Arbeit sperren, ohne dass er den Fokus verliert. */
function beschaeftigt(knopf, text) {
  const vorher = knopf.textContent;
  knopf.setAttribute('aria-disabled', 'true'); knopf.textContent = text;
  return () => { knopf.removeAttribute('aria-disabled'); knopf.textContent = vorher; };
}
const gesperrt = (knopf) => knopf.getAttribute('aria-disabled') === 'true';

/* Gemini: Schlüssel eingeben, vom Server prüfen und speichern lassen. */
function geminiZeichnen(element, z, helfer) {
  element.innerHTML = `${ursacheKasten(z)}
    <p>Hol dir einen kostenlosen Schlüssel bei <a href="${SCHLUESSEL_SEITE}" target="_blank" rel="noopener noreferrer">Google AI Studio (öffnet ein neues Fenster)</a> und füge ihn hier ein.</p>
    <form class="ki-form" novalidate>
      <label class="feld">Gemini-Schlüssel
        <input type="password" class="ki-eingabe" maxlength="200" autocomplete="off" spellcheck="false" aria-describedby="kiSchluesselHilfe" data-fokus></label>
      <p class="muted klein" id="kiSchluesselHilfe">Er wird bei Google geprüft und nur bei Erfolg auf diesem Rechner in der Datei <code>.env</code> gespeichert.</p>
      <p class="ki-fehler" role="alert" hidden></p>
      <div class="reihe ende"><button type="submit" class="btn primary">Speichern</button></div>
    </form>`;
  const form = element.querySelector('form'), feld = form.querySelector('input');
  const knopf = form.querySelector('button'), fehler = form.querySelector('.ki-fehler');
  const melden = (text) => {
    fehler.textContent = text; fehler.hidden = !text;
    if (text) { feld.setAttribute('aria-invalid', 'true'); feld.focus(); }
    else feld.removeAttribute('aria-invalid');
  };
  form.onsubmit = (ev) => {
    ev.preventDefault();
    helfer.senden(knopf, '/ki/gemini/schluessel', { schluessel: feld.value }, melden, 'Prüfe …');
  };
  return true;
}

/* Claude: ohne CLI installieren, mit CLI nur anmelden. */
function claudeZeichnen(element, z, helfer) {
  if (z.zustand === 'nicht_eingerichtet') {
    element.innerHTML = `${ursacheKasten(z)}
      <p>genut kann Claude Code mit dem offiziellen Installer von claude.ai einrichten, ohne Administratorrechte. Du brauchst dafür ein Claude-Abo oder ein Anthropic-Konto.</p>
      <p class="ki-fehler" role="alert" hidden></p>
      <div class="reihe ende"><button type="button" class="btn primary" data-fokus>${helfer.gescheitert ? NOCHMAL : 'Claude installieren'}</button></div>`;
    const knopf = element.querySelector('button'), fehler = element.querySelector('.ki-fehler');
    knopf.onclick = () => helfer.senden(knopf, '/ki/claude/installieren', undefined,
      (text) => { fehler.textContent = text; fehler.hidden = !text; }, 'Starte …');
    return true;
  }
  if (z.aktion !== 'anmelden') { ursacheZeichnen(element, z); return false; }
  element.innerHTML = `${ursacheKasten(z)}
    <p class="ki-anleitung">Öffne ein Terminal, gib <code>claude</code> ein und melde dich an.</p>
    <p class="muted klein">Komm danach hierher zurück und wähle „Erneut prüfen“.</p>`;
  return false;
}

/* Lokal: Ollama fehlt → Setup-Befehl; läuft nicht → starten; läuft → Modell wählen. */
function ollamaZeichnen(element, z, helfer) {
  if (z.aktion === 'starten') {
    element.innerHTML = `${ursacheKasten(z)}
      <p>Ollama ist installiert, läuft aber gerade nicht.</p>
      <p class="ki-fehler" role="alert" hidden></p>
      <div class="reihe ende"><button type="button" class="btn primary" data-fokus>${helfer.gescheitert ? NOCHMAL : 'Ollama starten'}</button></div>`;
    const knopf = element.querySelector('button'), fehler = element.querySelector('.ki-fehler');
    knopf.onclick = () => helfer.senden(knopf, '/ki/ollama/starten', undefined,
      (text) => { fehler.textContent = text; fehler.hidden = !text; }, 'Starte …');
    return true;
  }
  if (z.zustand !== 'nicht_eingerichtet') { ursacheZeichnen(element, z); return false; }
  // Ohne Ursache fehlt Ollama selbst; mit Ursache läuft es, aber das Modell fehlt.
  if (!z.ursache) { ollamaFehlt(element, z); return false; }
  modellWahl(element, z, helfer);
  return true;
}

function ollamaFehlt(element, z) {
  // Server und Browser laufen auf demselben Rechner, also gilt das System des Browsers.
  const windows = /win/i.test(navigator.userAgentData?.platform || navigator.platform || '');
  const befehl = windows ? '.\\setup.bat -Nur lokal' : './setup.sh --nur lokal';
  element.innerHTML = `${ursacheKasten(z)}
    <p>Für die lokale KI brauchst du das Programm Ollama. Das Setup von genut richtet es ein:</p>
    <ol class="ki-liste">
      <li>Öffne ${windows ? 'die PowerShell' : 'ein Terminal'} im genut-Ordner.</li>
      <li>Führe diesen Befehl aus und beantworte die Fragen:</li>
    </ol>
    <div class="ki-befehl"><code>${esc(befehl)}</code><button type="button" class="btn klein">Kopieren</button></div>
    <p class="muted klein">Wenn das Setup fertig ist, wähle „Erneut prüfen“. Lokal ist experimentell und braucht einen kräftigen Rechner.</p>`;
  element.querySelector('button').onclick = async () => {
    try {
      await navigator.clipboard.writeText(befehl);
      H.toast('Befehl kopiert');
    } catch (e) { // ohne Zwischenablage: Text markieren, dann reicht Strg+C
      getSelection().selectAllChildren(element.querySelector('.ki-befehl code'));
      H.toast('Befehl ist markiert. Kopiere ihn mit Strg+C.', true);
    }
  };
}

const URTEIL = { gut: ['läuft gut', 'ok'], langsam: ['läuft langsam', 'warn'], zu_gross: ['zu groß', 'err'] };
const zahl = (n) => Number(n).toLocaleString('de-DE', { maximumFractionDigits: 1 });

function modellZeile({ name, gewaehlt, marken, texte }) {
  return `<label class="ki-modell"><input type="radio" name="kiModell" value="${esc(name)}"${gewaehlt ? ' checked' : ''}>
    <span class="ki-modell-text"><span class="ki-modell-kopf"><strong>${esc(name)}</strong>${marken}</span>${texte}</span></label>`;
}

async function modellWahl(element, z, helfer) {
  element.innerHTML = `${ursacheKasten(z)}<p class="muted">Rechner und Modelle werden geprüft …</p>`;
  let v;
  try { v = await H.api('GET', '/ki/ollama/vorschlaege'); } catch (e) {
    if (element.isConnected) element.lastElementChild.outerHTML = `<p class="ki-fehler" role="alert">${esc(e.message)}. Wähle „Erneut prüfen“.</p>`;
    return;
  }
  if (!element.isConnected) return; // Dialog inzwischen geschlossen oder neu gezeichnet
  const p = v.profil;
  const rechner = [`${zahl(p.ram_gb)} GB Arbeitsspeicher`,
    p.grafik === 'keine' ? 'keine passende Grafikkarte' : `${zahl(p.grafik_gb)} GB ${p.grafik === 'apple' ? 'gemeinsamer Speicher' : 'Grafikspeicher'}`,
    p.frei_gb == null ? '' : `${zahl(p.frei_gb)} GB frei`].filter(Boolean).join(', ');
  const vorschlaege = v.vorschlaege.map((m) => modellZeile({
    name: m.name, gewaehlt: m.vorgewaehlt,
    marken: `<span class="chip ${URTEIL[m.urteil][1]}">${URTEIL[m.urteil][0]}</span>${m.vorhanden ? '<span class="chip">schon geladen</span>' : ''}`,
    texte: `<span class="klein">${esc(m.stufe)}, ${zahl(m.download_gb)} GB Download</span><span class="muted klein">${esc(m.begruendung)}</span>
      ${m.platz_warnung && !m.vorhanden ? '<span class="ki-platz klein"><span aria-hidden="true">⚠ </span>Wenig freier Speicherplatz: der Download passt vielleicht nicht.</span>' : ''}`,
  })).join('');
  const vorhanden = v.vorhanden.map((m) => modellZeile({
    name: m.name, gewaehlt: false, marken: '<span class="chip">schon geladen</span>',
    texte: `<span class="klein">${zahl(m.groesse_gb)} GB, versteht Bilder</span>`,
  })).join('');
  element.innerHTML = `${ursacheKasten(z)}
    <p class="muted klein">Dein Rechner: ${esc(rechner)}.</p>
    ${v.keins_gut ? '<p class="ki-warnung" role="status">Eine lokale KI läuft auf diesem Rechner nicht gut – Gemini empfohlen.</p>' : ''}
    <form class="ki-form">
      <fieldset class="ki-modelle"><legend>Vorschläge</legend>${vorschlaege}</fieldset>
      ${vorhanden ? `<fieldset class="ki-modelle"><legend>Schon auf diesem Rechner</legend>${vorhanden}</fieldset>` : ''}
      <p class="ki-fehler" role="alert" hidden></p>
      <div class="reihe ende"><button type="submit" class="btn primary">Laden</button></div>
    </form>`;
  const form = element.querySelector('form'), knopf = form.querySelector('button[type="submit"]'), fehler = form.querySelector('.ki-fehler');
  const geladen = new Set([...v.vorschlaege.filter((m) => m.vorhanden), ...v.vorhanden].map((m) => m.name));
  const wahl = () => form.querySelector('input[name="kiModell"]:checked')?.value;
  // Nach einem Fehlschlag bleibt das gewählte Modell gewählt, sonst lüde der zweite Versuch ein anderes.
  const zuletzt = helfer.gescheitert ? helfer.wahl?.name : undefined;
  const radio = [...form.querySelectorAll('input[name="kiModell"]')].find((r) => r.value === zuletzt);
  if (radio) radio.checked = true;
  const beschriften = () => {
    knopf.textContent = radio && wahl() === zuletzt ? NOCHMAL : geladen.has(wahl()) ? 'Verwenden' : 'Laden';
  };
  form.onchange = beschriften;
  beschriften();
  form.onsubmit = (ev) => {
    ev.preventDefault();
    helfer.senden(knopf, '/ki/ollama/modell', { name: wahl() },
      (text) => { fehler.textContent = text; fehler.hidden = !text; }, 'Starte …');
  };
}

const EINRICHTUNG = { claude_code: claudeZeichnen, gemini: geminiZeichnen, ollama: ollamaZeichnen };

/** Zeigt einen Einrichtungsauftrag und fragt ihn jede Sekunde ab, solange lebt() wahr ist.
 *  ende(auftrag) bekommt den beendeten Auftrag (null: der Server kennt ihn nicht mehr). */
async function auftragZeigen(element, name, kennung, lebt, ende) {
  element.innerHTML = `<p><strong>Einrichtung von ${esc(NAMEN[name])} läuft …</strong></p>
    <div class="fortschritt ki-balken unbestimmt" role="progressbar" aria-label="Fortschritt der Einrichtung" aria-valuemin="0" aria-valuemax="100"><span></span></div>
    <p class="ki-prozent klein" aria-live="off" hidden></p>
    <div class="log ki-ausgabe" role="log" aria-live="off" aria-label="Ausgabe" tabindex="0" hidden></div>
    <p class="muted klein">Du kannst den Dialog schließen. Die Einrichtung läuft weiter, und beim nächsten Öffnen siehst du den Stand.</p>`;
  const balken = element.querySelector('.ki-balken'), prozent = element.querySelector('.ki-prozent');
  const ausgabe = element.querySelector('.ki-ausgabe');
  let letzte = '';
  while (lebt()) {
    let a = null;
    try { a = await H.api('GET', `/ki/auftraege/${encodeURIComponent(kennung)}`); } catch (e) {
      if (e.detail === 'Auftrag nicht gefunden') { if (lebt()) ende(null); return; }
      // Server kurz nicht erreichbar: weiter versuchen
    }
    if (!lebt()) return;
    if (a) {
      if (a.status !== 'laeuft') { ende(a); return; }
      if (a.fortschritt != null) {
        balken.classList.remove('unbestimmt');
        balken.setAttribute('aria-valuenow', a.fortschritt);
        balken.firstElementChild.style.width = `${a.fortschritt}%`;
        prozent.textContent = `${a.fortschritt} %`; prozent.hidden = false;
      }
      if (a.meldung && a.meldung !== letzte) {
        letzte = a.meldung;
        // Beim Installieren die Ausgabe sammeln; beim Download und Start zählt nur der neueste Stand.
        if (a.schritt !== 'installieren') ausgabe.replaceChildren();
        const zeile = document.createElement('div');
        zeile.textContent = a.meldung;
        ausgabe.appendChild(zeile); ausgabe.hidden = false;
        while (ausgabe.childElementCount > 200) ausgabe.firstElementChild.remove();
        ausgabe.scrollTop = ausgabe.scrollHeight;
      }
    }
    await new Promise((weiter) => setTimeout(weiter, TAKT));
  }
}

function einrichtenDialog(name) {
  let gezeigt = null;
  let auftrag = null;           // Kennung des Auftrags, den der Dialog verfolgt
  let fehlschlag = '';          // Meldung des zuletzt gescheiterten Auftrags
  let letzterBody;              // was zuletzt abgeschickt wurde (nie der Schlüssel)
  const beendet = new Set();    // ein veralteter Zustand darf keinen beendeten Auftrag neu zeigen
  const pruefen = async (knopf) => {
    if (knopf && gesperrt(knopf)) return;
    const frei = knopf && beschaeftigt(knopf, 'Prüfe …');
    if (knopf) fehlschlag = '';
    try {
      await laden(true, true);
      if (lebt()) zeichnen(true);
    } catch (e) { H.toast(e.message, true); }
    finally { if (frei) frei(); }
  };
  const d = dialogZeigen(`${NAMEN[name]} einrichten`, [{ text: 'Erneut prüfen', klick: pruefen, primaer: true }]);
  dlgKi = name;
  const lebt = () => d.marke === offen && dlg.open;
  const nochmal = d.leiste.lastElementChild;
  /** Fokus zurückholen, wenn das fokussierte Element beim Neuzeichnen verschwunden ist. */
  const fokusSichern = () => {
    const f = document.activeElement;
    if (f && f !== dlg && dlg.contains(f) && !f.hidden) return;
    (d.inhalt.querySelector('[data-fokus]') || d.leiste.querySelector('.primary:not([hidden])') || d.leiste.querySelector('button')).focus();
  };
  const folgen = (kennung) => {
    auftrag = kennung; fehlschlag = '';
    zeichnen(true);
  };
  const auftragEnde = async (kennung, a) => {
    beendet.add(kennung); auftrag = null;
    fehlschlag = a && a.status === 'fehler' ? a.meldung || 'Die Einrichtung ist gescheitert' : '';
    await laden(true);
    if (!lebt()) return;
    zeichnen(true);
    // Während des Auftrags liegt der Fokus ersatzweise auf „Schließen“; nach einem Fehler zur Hauptaktion.
    if (fehlschlag && document.activeElement === d.leiste.firstElementChild) d.inhalt.querySelector('[data-fokus]')?.focus();
  };
  const senden = async (knopf, pfad, body, melden, arbeitet) => {
    if (gesperrt(knopf)) return;
    const frei = beschaeftigt(knopf, arbeitet);
    melden('');
    letzterBody = body && body.name ? { name: body.name } : undefined;
    try {
      const antwort = await H.api('POST', pfad, body);
      if (antwort.name) { // sofort erledigt: die Antwort ist der neue KiZustand
        fehlschlag = '';
        await laden(true);
        if (lebt()) zeichnen(true);
      } else {
        if (lebt()) folgen(antwort.auftrag);
        laden(true); // der Schalter kennt dann den laufenden Auftrag, auch wenn der Dialog zugeht
      }
    } catch (e) {
      await laden(true); // z. B. „läuft schon“ oder „ist schon installiert“: der Stand ist veraltet
      if (!lebt()) { H.toast(e.message, true); return; }
      zeichnen(false);
      if (knopf.isConnected) melden(e.message); else H.toast(e.message, true);
    } finally { frei(); if (lebt()) fokusSichern(); }
  };
  const zeichnen = (immer) => {
    const z = zustandVon(name);
    if (!auftrag && z && z.auftrag && !beendet.has(z.auftrag)) auftrag = z.auftrag;
    const kennung = auftrag ? `auftrag|${auftrag}` : z ? `${z.zustand}|${z.ursache}|${z.aktion}` : '';
    // Eingaben im Dialog nicht ohne Grund verwerfen; ein laufender Auftrag wird nie doppelt abgefragt.
    if (kennung === gezeigt && (auftrag || !immer)) return;
    gezeigt = kennung;
    d.inhalt.replaceChildren();
    const element = document.createElement('div');
    d.inhalt.appendChild(element);
    nochmal.hidden = Boolean(auftrag);
    let eigeneAktion = false;
    if (auftrag) {
      const meine = auftrag;
      if (z && z.zustand === 'bereit') {
        d.inhalt.insertAdjacentHTML('afterbegin', `<p class="ki-ursache ki-bereit"><span aria-hidden="true">✓</span><span><strong>${esc(NAMEN[name])} ist bereit</strong> und du kannst sie schon nutzen.</span></p>`);
      }
      auftragZeigen(element, name, meine, () => lebt() && element.isConnected, (a) => auftragEnde(meine, a));
    } else if (!z) {
      element.innerHTML = '<p class="muted">Zustand wird geprüft …</p>';
    } else if (z.zustand === 'bereit') {
      element.innerHTML = `<p class="ki-ursache ki-bereit"><span aria-hidden="true">✓</span><span><strong>${esc(NAMEN[name])} ist bereit.</strong> Du kannst sie jetzt im KI-Schalter wählen.</span></p>`;
    } else {
      eigeneAktion = (EINRICHTUNG[name] || ursacheZeichnen)(element, z, {
        pruefen: () => pruefen(), folgen, senden, gescheitert: Boolean(fehlschlag), wahl: letzterBody });
    }
    if (fehlschlag && !auftrag) {
      const p = document.createElement('p');
      p.className = 'ki-fehler'; p.setAttribute('role', 'alert'); p.textContent = fehlschlag;
      d.inhalt.prepend(p);
    }
    nochmal.classList.toggle('primary', !eigeneAktion);
    fokusSichern();
  };
  zeichnen(true);
  d.inhalt.querySelector('[data-fokus]')?.focus(); // direkt ins Feld bzw. auf die Hauptaktion
  laden().then(() => { if (lebt()) zeichnen(false); });
}

/* ---------------- Vor jedem Auftrag (FR-010, FR-011) ---------------- */
async function wechseln(slug, name, knopf) {
  knopf.disabled = true;
  try {
    await H.api('PATCH', `/projekte/${encodeURIComponent(slug)}`, { modell: name });
    dlg.close();
    H.toast(`KI dieses Projekts: ${NAMEN[name]}. Starte den Auftrag noch einmal.`);
    window.dispatchEvent(new HashChangeEvent('hashchange')); // Seite und Schalter neu zeichnen
  } catch (e) { knopf.disabled = false; H.toast(e.message, true); }
}

async function vorAuftrag({ art, slug, modell }) {
  if (OHNE_KI.includes(art)) return true;
  const s = await laden();
  if (!s) return true; // Zustände unbekannt: wie ohne dieses Modul
  const einrichten = (name) => ({ text: `${NAMEN[name]} einrichten`, klick: () => einrichtenDialog(name) });
  if (s.keine_bereit) {
    const d = dialogZeigen('Richte zuerst eine KI ein', s.zustaende.map((z) => einrichten(z.name)));
    d.inhalt.innerHTML = `<p>Der Auftrag wurde nicht gestartet, weil noch keine KI bereit ist.</p>
      <ul class="ki-liste">${s.zustaende.map((z) => `<li>${esc(beschreibung(z))}</li>`).join('')}</ul>`;
    return false;
  }
  if (!NAMEN[modell]) return true; // wird nicht geprüft (z. B. andere Schnittstelle)
  const z = zustandVon(modell);
  if (z && z.zustand === 'bereit') return true;
  const aktionen = s.zustaende.filter((x) => x.zustand === 'bereit' && x.name !== modell)
    .map((x, i) => ({ text: `Zu ${NAMEN[x.name]} wechseln`, primaer: i === 0, klick: (b) => wechseln(slug, x.name, b) }));
  if (z) aktionen.unshift(einrichten(modell));
  const d = dialogZeigen(`${NAMEN[modell]} ist nicht bereit`, aktionen, 'Abbrechen');
  const grund = !z ? 'sie ist in der Konfiguration nicht ausgewählt' : (z.ursache || WORT[z.zustand]);
  d.inhalt.innerHTML = `<p>Der Auftrag wurde nicht gestartet. Dieses Projekt nutzt <strong>${esc(NAMEN[modell])}</strong> (${esc(grund)}).</p>
    <p class="muted klein">Wechsle die KI dieses Projekts${z ? ` oder richte ${esc(NAMEN[modell])} ein` : ''}.</p>`;
  return false;
}

/* ---------------- Start des Moduls ---------------- */
export function start(hooks) {
  H = hooks;
  if (!document.querySelector('link[data-ki-einrichtung]')) {
    const l = document.createElement('link');
    l.rel = 'stylesheet'; l.href = '/ui/funktionen/ki_einrichtung.css'; l.dataset.kiEinrichtung = '1';
    document.head.appendChild(l);
  }
  H.kiSchalter(schalterGezeichnet);
  H.vorAuftrag(vorAuftrag);
  H.bereich('kopf-hinweis', (element) => { hinweisEl = element; hinweisZeichnen(); });
  // „Öffnen“ des Schalters: Fokus hinein oder Zeiger darüber. Der Server speichert Ergebnisse kurz.
  const schalter = document.querySelector('.ki-schalter');
  schalter.addEventListener('focusin', (ev) => { if (!schalter.contains(ev.relatedTarget)) laden(); });
  schalter.addEventListener('pointerenter', () => laden());
  laden(); // nicht abwarten: eine langsame Erkennung hält die App nicht auf
}
