// Projekt-Austausch (Feature 007). Wird von ui/app.js als Modul geladen: export async function start(hooks).
// Haken beim Herunterladen (US1), Import per Knopf oder Ziehen auf die Projektliste (US2), Herkunft (US3).
let H = null;
const esc = (s) => H.esc(s);

/* ---------------- Export: Haken beim Herunterladen ---------------- */
function exportHaken(el, { p, link }) {
  const ohne = link.getAttribute('href');
  const mit = `/api/austausch/projekte/${encodeURIComponent(p.slug)}/download`;
  el.innerHTML = `<div class="at-export">
    <label class="at-haken"><input type="checkbox" checked autocomplete="off"><span>Zum Importieren für Freunde (mit Projektdaten)</span></label>
    <p class="klein muted">Freunde mit genut können die Datei als Projekt importieren. Ohne Haken: nur die Lernseite.</p></div>`;
  const haken = el.querySelector('input');
  const setzen = () => link.setAttribute('href', haken.checked ? mit : ohne);
  haken.onchange = setzen;
  setzen();
}

/* ---------------- Import: Knopf und Ziehen ---------------- */
let importLaeuft = false; // gilt über Seitenwechsel: nie zwei Importe gleichzeitig

function knopfZustand(knopf) {
  knopf.disabled = importLaeuft;
  knopf.textContent = importLaeuft ? 'Importiere …' : 'Projekt importieren';
}
/** Auch die Liste kann während des Imports neu gezeichnet worden sein. */
const alleKnoepfe = () => document.querySelectorAll('.at-import-btn').forEach(knopfZustand);

async function importieren(dateien) {
  if (!dateien.length) return;
  if (importLaeuft) { H.toast('Es läuft schon ein Import. Bitte warten.', true); return; }
  const datei = dateien[0];
  if (!/\.html?$/i.test(datei.name)) { H.toast('Nur .html-Dateien aus genut lassen sich importieren', true); return; }
  importLaeuft = true;
  alleKnoepfe();
  H.toast(dateien.length > 1 ? 'Nur die erste Datei wird importiert. Importiere …' : 'Importiere …');
  try {
    const daten = new FormData();
    daten.append('datei', datei);
    const r = await H.api('POST', '/austausch/import', daten);
    let diagrammFehler = '';
    // Das Projekt gibt es jetzt schon: Ein Fehler beim Zeichnen darf das Öffnen nicht verhindern.
    try { await H.diagrammeZeichnen(r.slug, H.toast); } catch (e) { diagrammFehler = `Diagramme nicht gezeichnet: ${e.message}`; }
    location.hash = `#/p/${encodeURIComponent(r.slug)}`;
    const offen = r.status?.fehler || 0;
    const ergebnis = `Importiert: ${r.name}` + (offen ? ` · ${offen} ${offen === 1 ? 'Element' : 'Elemente'} nicht bestätigt` : '');
    const probleme = [r.warnung, diagrammFehler].filter(Boolean).join(' · ');
    H.toast(probleme ? `${ergebnis} · ${probleme}` : ergebnis, !!probleme);
  } catch (e) {
    H.toast(e.message, true);
  } finally {
    importLaeuft = false;
    alleKnoepfe();
  }
}

function listenAktionen(el, { liste }) {
  el.innerHTML = `<button type="button" class="btn at-import-btn"></button>
    <input type="file" class="at-datei" accept=".html,.htm,text/html" hidden>`;
  const knopf = el.querySelector('button'), eingabe = el.querySelector('input');
  knopfZustand(knopf);
  knopf.onclick = () => eingabe.click();
  eingabe.onchange = () => {
    const dateien = Array.from(eingabe.files);
    eingabe.value = ''; // dieselbe Datei darf noch einmal gewählt werden
    importieren(dateien);
  };

  // `liste` entsteht bei jedem Zeichnen neu, so melden sich die Handler nie doppelt an.
  const istDatei = (ev) => Array.from(ev.dataTransfer?.types || []).includes('Files');
  liste.addEventListener('dragover', (ev) => {
    if (!istDatei(ev)) return;
    ev.preventDefault(); // auch während eines Imports, sonst öffnet der Browser die Datei
    ev.dataTransfer.dropEffect = 'copy';
    liste.classList.add('at-ziel');
  });
  liste.addEventListener('dragleave', (ev) => {
    if (!liste.contains(ev.relatedTarget)) liste.classList.remove('at-ziel');
  });
  liste.addEventListener('drop', (ev) => {
    if (!istDatei(ev)) return;
    ev.preventDefault();
    liste.classList.remove('at-ziel');
    importieren(Array.from(ev.dataTransfer.files));
  });
}

/* ---------------- Herkunft ---------------- */
let herkunftAnfrage = null;

/** Eine Anfrage je Seitenaufbau: app.js füllt alle Karten in einem Zug, danach wird das Promise verworfen. */
function herkunftHolen() {
  if (!herkunftAnfrage) {
    herkunftAnfrage = H.api('GET', '/austausch/herkunft')
      .then((d) => d?.projekte || {})
      .catch((e) => { console.warn('Herkunft nicht geladen:', e.message); return {}; });
    queueMicrotask(() => { herkunftAnfrage = null; });
  }
  return herkunftAnfrage;
}
async function herkunftVon(slug) {
  const alle = await herkunftHolen();
  return Object.hasOwn(alle, slug) ? alle[slug] : null;
}
const datumText = (s) => new Date(s).toLocaleDateString('de-AT', { day: '2-digit', month: '2-digit', year: 'numeric' });
const herkunftText = (h) => `importiert am ${datumText(h.importiert_am)} aus „${h.dateiname}“`;

async function projektChip(el, p) {
  const h = await herkunftVon(p.slug);
  if (!h) return;
  const text = herkunftText(h);
  el.innerHTML = `<span class="chip" title="${esc(text[0].toUpperCase() + text.slice(1))}">importiert</span>`;
}

async function fotosHinweis(el, p) {
  const h = await herkunftVon(p.slug);
  if (!h) return;
  el.innerHTML = `<div class="karte hinweis at-hinweis">Die Original-Fotos liegen beim Absender (${esc(herkunftText(h))}). Du kannst eigene Fotos ergänzen.</div>`;
}

/* ---------------- Start ---------------- */
export async function start(hooks) {
  H = hooks;
  if (!document.querySelector('link[data-austausch]')) {
    const l = document.createElement('link');
    l.rel = 'stylesheet'; l.href = '/ui/funktionen/austausch.css'; l.dataset.austausch = '1';
    document.head.appendChild(l);
  }
  H.bereich('export-herunterladen', exportHaken);
  H.bereich('projektliste-aktionen', listenAktionen);
  H.bereich('projekt-chips', projektChip);
  H.bereich('fotos-hinweis', fotosHinweis);
}
