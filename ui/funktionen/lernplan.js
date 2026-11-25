// Lernplaner (Feature 004). Wird von ui/app.js als Modul geladen: export function start(hooks).
// Liste, Dialog „Neuer Plan“/„Plan bearbeiten“, Planansicht (US1), Haken und Neu verteilen (US2), Bearbeiten, Löschen (US3).
let H = null;
const esc = (s) => H.esc(s);

const WOCHENTAGE = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'];
const WOCHENTAGE_LANG = ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag', 'Sonntag'];

/* ---------------- Datum ---------------- */
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const aus = (s) => { const [j, m, t] = String(s).split('-').map(Number); return new Date(j, m - 1, t); };
const datumText = (s) => aus(s).toLocaleDateString('de-AT', { day: '2-digit', month: '2-digit', year: 'numeric' });
const kurzDatum = (s) => aus(s).toLocaleDateString('de-AT', { day: '2-digit', month: '2-digit' });
const heuteIso = () => iso(new Date());
const plusTage = (d, n) => { const x = new Date(d.getFullYear(), d.getMonth(), d.getDate() + n); return x; };
const wochentag = (s) => (aus(s).getDay() + 6) % 7; // Montag = 0
const montagVon = (s) => iso(plusTage(aus(s), -wochentag(s)));

/** Gleiche Regel wie lerntage() im Server: von max(start, heute) bis zum Tag vor dem Termin, gewählte Wochentage. */
function zaehleLerntage(start, termin, wochentage, heute) {
  const wt = new Set(wochentage);
  let tag = aus(start > heute ? start : heute);
  const ende = aus(termin);
  let n = 0;
  while (tag < ende) {
    if (wt.has((tag.getDay() + 6) % 7)) n++;
    tag = plusTage(tag, 1);
  }
  return n;
}

/* ---------------- Bausteine ---------------- */
function fortschrittHtml(f) {
  const gesamt = f.gesamt + f.wiederholung_gesamt, erl = f.erledigt + f.wiederholung_erledigt;
  const proz = gesamt ? Math.round(erl / gesamt * 100) : 0;
  return `<div class="lp-fortschritt" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${proz}" aria-label="Fortschritt"><span class="lp-fortschritt-fuell" style="width:${proz}%"></span></div>
    <div class="lp-fortschritt-text">${f.erledigt} von ${f.gesamt} Themen${f.wiederholung_gesamt ? ` · Wiederholung ${f.wiederholung_erledigt} von ${f.wiederholung_gesamt}` : ''}</div>`;
}

function planKarte(z) {
  return `<a class="lp-plan" href="#/lernplan/${encodeURIComponent(z.id)}">
    <div class="lp-plan-kopf"><span class="lp-plan-name">${esc(z.name)}</span>
      ${z.fertig ? '<span class="chip ok">fertig</span>' : ''}
      ${z.ueberfaellig ? `<span class="chip lp-chip-ueberfaellig">${z.ueberfaellig} überfällig</span>` : ''}</div>
    <div class="lp-plan-meta"><span>Prüfung ${esc(datumText(z.termin))}</span><span>${esc((z.projekte || []).join(', '))}</span></div>
    ${fortschrittHtml(z.fortschritt)}</a>`;
}

/** Haken (nur Kästchen, Beschriftung unsichtbar). `daten` = data-Attribute als Text. */
function hakenHtml(label, an, daten) {
  return `<label class="lp-haken lp-haken-nur"><input type="checkbox" ${an ? 'checked' : ''} aria-label="${esc(label)}" ${daten}></label>`;
}

/** Eine Themenzeile (ein Stück). Stücke ohne Datum (noch nicht verteilt) bekommen keinen Haken. */
function themaZeile(s) {
  const titel = esc(s.titel) + (s.teile > 1 ? ` (${esc(s.teil)}/${esc(s.teile)})` : '');
  const erl = s.status === 'erledigt';
  const cls = ['lp-thema', erl ? 'erledigt' : '', s.status === 'ueberfaellig' ? 'ueberfaellig' : ''].filter(Boolean).join(' ');
  const chips = [
    erl ? '<span class="chip ok">erledigt</span>' : '',
    s.status === 'ueberfaellig' ? '<span class="chip lp-chip-ueberfaellig">überfällig</span>' : '',
    s.urspruenglich ? `<span class="chip lp-chip-verschoben">verschoben von ${esc(kurzDatum(s.urspruenglich))}</span>` : '',
  ].join('');
  const haken = s.datum ? hakenHtml(`${s.titel}${s.teile > 1 ? ` (${s.teil}/${s.teile})` : ''} erledigt`, erl,
    `data-stueck="1" data-projekt="${esc(s.projekt)}" data-thema="${esc(s.thema_id)}" data-von="${esc(s.von)}" data-bis="${esc(s.bis)}" data-bis-gespeichert="${esc(s.bis_gespeichert ?? s.bis)}"`) : '';
  return `<li class="${cls}">${haken}<a class="lp-thema-titel" href="${esc(s.link)}">${titel}</a>
    <span class="chip">${esc(s.projekt_name)}</span><span class="chip">Umfang ${esc(Math.round(s.umfang))}</span>${chips}</li>`;
}

function wiederholungHaken(t) {
  return t.wiederholung ? hakenHtml(`Wiederholung am ${datumText(t.datum)} erledigt`, t.wiederholung_erledigt, `data-wiederholung="${esc(t.datum)}"`) : '';
}

function tagKarte(t, heute) {
  const cls = ['lp-tag', t.datum === heute ? 'heute' : '', t.datum < heute ? 'vergangen' : '', t.wiederholung ? 'wiederholung' : ''].filter(Boolean).join(' ');
  const frei = !t.themen.length && !t.wiederholung;
  return `<section class="${cls}" aria-label="${esc(WOCHENTAGE_LANG[t.wochentag])} ${esc(datumText(t.datum))}">
    <div class="lp-tag-kopf"><span class="lp-tag-datum">${esc(WOCHENTAGE[t.wochentag])}, ${esc(datumText(t.datum))}</span>
      ${t.datum === heute ? '<span class="chip akz">heute</span>' : ''}
      ${t.wiederholung ? '<span class="chip lp-chip-wiederholung">Wiederholung</span>' : ''}
      ${frei ? '<span class="chip lp-chip-frei">frei</span>' : ''}
      ${t.voll ? '<span class="chip warn">voll</span>' : ''}</div>
    ${t.themen.length ? `<ul class="lp-themen">${t.themen.map(themaZeile).join('')}</ul>` : ''}
    ${t.wiederholung ? `<div class="lp-wdh-zeile ${t.wiederholung_erledigt ? 'erledigt' : ''}">${wiederholungHaken(t)}<span class="muted">${t.themen.length ? 'Auch dieser Tag ist Wiederholung.' : 'Alles noch einmal durchgehen.'}</span>${t.wiederholung_erledigt ? '<span class="chip ok">erledigt</span>' : ''}</div>` : ''}</section>`;
}

/* ---------------- Liste ---------------- */
async function seiteLernplaene(ziel) {
  const d = await H.api('GET', '/lernplaene');
  const aktuell = d.aktuell || [], archiv = d.archiv || [];
  ziel.innerHTML = `<div class="kopfzeile"><h1>Lernplan</h1>
      <button class="btn primary" id="lpNeu" type="button">Neuer Plan</button></div>
    ${aktuell.length ? `<div class="lp-liste">${aktuell.map(planKarte).join('')}</div>`
      : '<p class="leer">Noch kein Plan. Lege einen an, dann verteilt der Lernplan die Themen auf die Tage bis zur Prüfung.</p>'}
    ${archiv.length ? `<details class="lp-archiv"><summary>Archiv (${archiv.length})</summary><div class="lp-liste">${archiv.map(planKarte).join('')}</div></details>` : ''}`;
  document.getElementById('lpNeu').onclick = () => dialogPlan();
}

/* ---------------- Dialog „Neuer Plan“ ---------------- */
/** Dialog „Neuer Plan“ (plan = null) oder „Plan bearbeiten“ (plan = Plan-Antwort, Formular vorbelegt).
 *  `nachSpeichern(antwort)` wird nach erfolgreichem Speichern (PATCH) aufgerufen. */
async function dialogPlan(plan = null, nachSpeichern = null) {
  let projekte;
  try {
    const alle = await H.api('GET', '/projekte');
    projekte = (await Promise.all(alle.map(async (p) => {
      try { return { slug: p.slug, name: p.name, themen: await H.api('GET', `/projekte/${encodeURIComponent(p.slug)}/themen`) }; }
      catch (e) { return null; }
    }))).filter((p) => p && p.themen.length);
  } catch (e) { H.toast(e.message, true); return; }

  const dlg = document.getElementById('dlg'), f = document.getElementById('dlgForm');
  const heute = heuteIso();
  const standardTage = plan ? plan.wochentage : [0, 1, 2, 3, 4];
  const imPlan = (p) => !!plan && plan.projekte.includes(p.slug);
  const weg = (p, t) => !!plan && (plan.ausgenommen || []).some((a) => a.projekt === p.slug && a.thema_id === t.id);
  const themaAn = (p, t) => imPlan(p) && !weg(p, t);
  f.innerHTML = `<div class="lp-dialog"><h2>${plan ? 'Plan bearbeiten' : 'Neuer Plan'}</h2>
    <label class="feld">Name<input type="text" name="name" maxlength="60" required value="${esc(plan ? plan.name : '')}" autocomplete="off" placeholder="z. B. Mathe-Schularbeit"></label>
    ${projekte.length ? `<fieldset class="lp-dialog" style="border:0;padding:0;margin:0;min-width:0"><legend class="eyebrow">Projekte und Themen</legend>
      ${projekte.map((p, i) => `<div class="lp-projekt" data-i="${i}">
        <div class="lp-projekt-kopf"><label class="lp-haken"><input type="checkbox" data-projekt="${i}" ${p.themen.some((t) => themaAn(p, t)) ? 'checked' : ''}><span class="lp-haken-text">${esc(p.name)}</span></label>
          <span class="muted" data-zaehler="${i}"></span>
          <button class="btn klein" type="button" data-auf="${i}" aria-expanded="false">Themen</button></div>
        <div class="lp-auswahl" data-liste="${i}" hidden>
          <div class="reihe"><button class="btn klein" type="button" data-alle="${i}">Alle</button><button class="btn klein" type="button" data-keine="${i}">Keine</button></div>
          ${p.themen.map((t, k) => `<div class="lp-thema"><label class="lp-haken"><input type="checkbox" data-thema="${i}:${k}" ${themaAn(p, t) ? 'checked' : ''}><span class="lp-haken-text">${esc(t.titel)}</span></label></div>`).join('')}
        </div></div>`).join('')}</fieldset>`
      : '<p class="lp-hinweis">Es gibt noch kein Projekt mit Inhalt. Erzeuge zuerst eine Lernseite.</p>'}
    <div class="reihe"><label class="feld">Startdatum<input type="date" name="start" value="${esc(plan ? plan.start : heute)}" required></label>
      <label class="feld">Prüfungstermin<input type="date" name="termin" required value="${esc(plan ? plan.termin : '')}" min="${esc(iso(plusTage(aus(heute), 1)))}"></label></div>
    <fieldset class="lp-tage" aria-label="Lerntage"><legend class="eyebrow" style="padding:0">Lerntage</legend>
      ${WOCHENTAGE.map((w, i) => `<label class="lp-tag-schalter" title="${esc(WOCHENTAGE_LANG[i])}"><input type="checkbox" class="lp-sr" name="wt" value="${i}" ${standardTage.includes(i) ? 'checked' : ''}><span>${w}</span></label>`).join('')}
    </fieldset>
    <div class="lp-vorschau" id="lpVorschau" role="status" aria-live="polite"></div>
    <div class="reihe ende"><button class="btn" type="button" id="lpAbbruch">Abbrechen</button><button class="btn primary" type="button" id="lpSpeichern">${plan ? 'Speichern' : 'Plan anlegen'}</button></div></div>`;

  const q = (s) => f.querySelector(s), qa = (s) => Array.from(f.querySelectorAll(s));
  const gewaehlt = () => projekte.map((p, i) => ({
    p, i, an: q(`[data-projekt="${i}"]`).checked,
    themen: p.themen.filter((_, k) => q(`[data-thema="${i}:${k}"]`).checked),
  }));
  const aktualisieren = () => {
    const g = gewaehlt();
    g.forEach(({ p, i, themen }) => { q(`[data-zaehler="${i}"]`).textContent = `${themen.length}/${p.themen.length}`; });
    const anzahl = g.filter((x) => x.an).reduce((s, x) => s + x.themen.length, 0);
    const tage = zaehleLerntage(q('[name=start]').value || heute, q('[name=termin]').value || heute, qa('[name=wt]:checked').map((c) => Number(c.value)), heute);
    q('#lpVorschau').textContent = `${tage} Lerntag${tage === 1 ? '' : 'e'}, ${anzahl} ${anzahl === 1 ? 'Thema' : 'Themen'}`;
  };
  f.onchange = (ev) => {
    const pr = ev.target.dataset && ev.target.dataset.projekt;
    if (pr !== undefined) qa(`[data-thema^="${pr}:"]`).forEach((c) => { c.checked = ev.target.checked; });
    else if (ev.target.dataset && ev.target.dataset.thema) {
      const i = ev.target.dataset.thema.split(':')[0];
      q(`[data-projekt="${i}"]`).checked = qa(`[data-thema^="${i}:"]`).some((c) => c.checked);
    }
    aktualisieren();
  };
  f.oninput = aktualisieren;
  f.onclick = (ev) => {
    const b = ev.target.closest('button'); if (!b) return;
    const d = b.dataset;
    if (d.auf !== undefined) {
      const l = q(`[data-liste="${d.auf}"]`); l.hidden = !l.hidden; b.setAttribute('aria-expanded', String(!l.hidden));
    } else if (d.alle !== undefined || d.keine !== undefined) {
      const i = d.alle !== undefined ? d.alle : d.keine;
      qa(`[data-thema^="${i}:"]`).forEach((c) => { c.checked = d.alle !== undefined; });
      q(`[data-projekt="${i}"]`).checked = d.alle !== undefined;
      aktualisieren();
    }
  };
  q('#lpAbbruch').onclick = () => dlg.close();
  const speichern = async () => {
    const g = gewaehlt().filter((x) => x.an && x.themen.length);
    const name = q('[name=name]').value.trim();
    if (!name) { q('[name=name]').focus(); H.toast('Bitte einen Namen eingeben.', true); return; }
    if (!g.length) { H.toast('Wähle mindestens ein Projekt mit einem Thema.', true); return; }
    const ausgenommen = [];
    g.forEach(({ p, themen }) => p.themen.forEach((t) => { if (!themen.includes(t)) ausgenommen.push({ projekt: p.slug, thema_id: t.id }); }));
    const body = {
      name, projekte: g.map((x) => x.p.slug), termin: q('[name=termin]').value, start: q('[name=start]').value || undefined,
      wochentage: qa('[name=wt]:checked').map((c) => Number(c.value)), ausgenommen,
    };
    if (!body.termin) { q('[name=termin]').focus(); H.toast('Bitte den Prüfungstermin wählen.', true); return; }
    const knopf = q('#lpSpeichern'); knopf.disabled = true;
    try {
      if (plan) {
        const neu = await H.api('PATCH', `/lernplaene/${encodeURIComponent(plan.id)}`, body);
        dlg.close();
        if (nachSpeichern) nachSpeichern(neu);
        H.toast('Plan gespeichert');
      } else {
        const neu = await H.api('POST', '/lernplaene', body);
        dlg.close();
        location.hash = `#/lernplan/${encodeURIComponent(neu.id)}`;
      }
    } catch (e) { H.toast(e.message, true); knopf.disabled = false; }
  };
  q('#lpSpeichern').onclick = speichern;
  f.onkeydown = (ev) => {
    if (ev.key === 'Enter' && ev.target.matches('input[type=text],input[type=date]')) {
      ev.preventDefault(); const k = f.querySelector('#lpSpeichern'); if (k) k.click();
    }
  };
  dlg.onclose = () => { f.onkeydown = null; f.onchange = null; f.oninput = null; f.onclick = null; };
  aktualisieren();
  dlg.returnValue = ''; dlg.showModal();
  q('[name=name]').focus();
}

/* ---------------- Planansicht ---------------- */
async function seitePlan(id, ziel) {
  zeichnePlan(await H.api('GET', `/lernplaene/${encodeURIComponent(id)}`), ziel);
}

function zeichnePlan(p, ziel) {
  const aktiv = document.activeElement && ziel.contains(document.activeElement) ? document.activeElement : null;
  const merke = aktiv && aktiv.matches('input[type=checkbox]') ? ['stueck', 'projekt', 'thema', 'von', 'bis', 'wiederholung'].map((k) => aktiv.dataset[k]) : null;
  const merkeKnopf = aktiv && aktiv.id === 'lpNeuVerteilen';
  const heute = heuteIso();
  const alleStuecke = p.tage.flatMap((t) => t.themen);
  // Heute und demnächst: überfällige offene Stücke, dann die nächsten drei Tage ab heute
  const ueberfaellig = alleStuecke.filter((s) => s.status === 'ueberfaellig');
  const kommende = p.tage.filter((t) => t.datum >= heute && (t.themen.length || t.wiederholung)).slice(0, 3);
  const woechen = new Map();
  p.tage.forEach((t) => { const k = montagVon(t.datum); if (!woechen.has(k)) woechen.set(k, []); woechen.get(k).push(t); });
  const liste = (items) => `<ul class="lp-themen">${items.join('')}</ul>`;
  const meldungen = (cls, arr) => arr && arr.length ? `<ul class="${cls}">${arr.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : '';
  const nvKnopf = '<div class="reihe"><button class="btn" type="button" data-nv="1">Neu verteilen</button></div>';
  const kommendeZeilen = kommende.map((t) => {
    const kopf = `<h3 style="font-size:1rem;margin:10px 0 6px">${esc(t.datum === heute ? 'Heute' : WOCHENTAGE_LANG[t.wochentag])}, ${esc(datumText(t.datum))}${t.wiederholung ? ' <span class="chip lp-chip-wiederholung">Wiederholung</span>' : ''}</h3>`;
    const wdh = t.wiederholung ? `<div class="lp-wdh-zeile ${t.wiederholung_erledigt ? 'erledigt' : ''}">${wiederholungHaken(t)}<span class="muted">${t.themen.length ? 'Auch dieser Tag ist Wiederholung.' : 'Alles noch einmal durchgehen.'}</span>${t.wiederholung_erledigt ? '<span class="chip ok">erledigt</span>' : ''}</div>` : '';
    return kopf + (t.themen.length ? liste(t.themen.map(themaZeile)) : '') + wdh;
  }).join('');

  ziel.innerHTML = `<p><a href="#/lernplan">← Alle Pläne</a></p>
    <div class="lp-kopf"><h1>${esc(p.name)}</h1>
      <div class="lp-plan-meta"><span>Prüfung ${esc(datumText(p.termin))}</span><span>Start ${esc(datumText(p.start))}</span>
        <span>${esc(p.wochentage.map((w) => WOCHENTAGE[w]).join(', '))}</span></div>
      <div class="reihe">${p.fertig ? '<span class="chip ok">Fertig</span>' : ''}${p.archiv ? '<span class="chip">Archiv</span>' : ''}
        ${p.ueberfaellig ? `<span class="chip lp-chip-ueberfaellig">${p.ueberfaellig} überfällig</span>` : ''}</div>
      ${fortschrittHtml(p.fortschritt)}
      ${p.fertig ? '<p class="lp-fertig" role="status">Fertig: alles erledigt, auch die Wiederholung.</p>' : ''}
      <div class="reihe">${p.archiv ? '' : '<button class="btn" type="button" id="lpNeuVerteilen" data-nv="1">Neu verteilen</button>'}
        <button class="btn" type="button" id="lpBearbeiten">Bearbeiten</button><button class="btn gefahr" type="button" id="lpLoeschen">Löschen</button></div></div>
    ${meldungen('lp-warnung', p.warnungen)}${meldungen('lp-hinweis', p.hinweise)}
    ${!p.archiv && p.hinweise && p.hinweise.length && !(p.unverteilt && p.unverteilt.length) ? nvKnopf : ''}
    ${p.unverteilt && p.unverteilt.length ? `<section class="lp-abschnitt"><h2>Noch nicht verteilt</h2>${liste(p.unverteilt.map(themaZeile))}${p.archiv ? '' : nvKnopf}</section>` : ''}
    ${!p.archiv && (ueberfaellig.length || kommende.length) ? `<section class="lp-abschnitt"><h2>Heute und demnächst</h2>
      ${ueberfaellig.length ? `<h3 style="font-size:1rem;margin:0 0 6px">Überfällig</h3>${liste(ueberfaellig.map(themaZeile))}` : ''}${kommendeZeilen}</section>` : ''}
    <section class="lp-abschnitt"><h2>Wochenansicht</h2>
      ${Array.from(woechen.entries()).map(([montag, tage]) => `<div class="lp-abschnitt"><h3>Woche ab ${esc(datumText(montag))}</h3>
        <div class="lp-woche">${tage.map((t) => tagKarte(t, heute)).join('')}</div></div>`).join('') || '<p class="leer">Keine Lerntage.</p>'}</section>`;

  ziel.onchange = (ev) => haken(ev, p, ziel);
  const nv = document.getElementById('lpNeuVerteilen');
  ziel.querySelectorAll('[data-nv]').forEach((b) => { b.onclick = () => neuVerteilen(p, ziel, b); });
  document.getElementById('lpBearbeiten').onclick = () => dialogPlan(p, (neu) => zeichnePlan(neu, ziel));
  document.getElementById('lpLoeschen').onclick = () => loeschen(p);
  if (merke) {
    const k = Array.from(ziel.querySelectorAll('input[type=checkbox]')).find((c) => ['stueck', 'projekt', 'thema', 'von', 'bis', 'wiederholung'].every((n, i) => c.dataset[n] === merke[i]));
    if (k) k.focus();
  } else if (merkeKnopf && nv) nv.focus();
}

async function loeschen(p) {
  const ok = await H.frage('Plan löschen?', `<p>Der Plan „${esc(p.name)}“ wird gelöscht. Die Projekte bleiben erhalten.</p>`, 'Löschen', true);
  if (!ok) return;
  try {
    await H.api('DELETE', `/lernplaene/${encodeURIComponent(p.id)}`);
    H.toast('Plan gelöscht');
    location.hash = '#/lernplan';
  } catch (e) { H.toast(e.message, true); }
}

/** Haken setzen: sofort umschalten, speichern, mit der Antwort neu zeichnen; bei Fehler zurücksetzen. */
async function haken(ev, p, ziel) {
  const c = ev.target;
  if (!c.matches || !c.matches('input[type=checkbox][data-stueck],input[type=checkbox][data-wiederholung]')) return;
  const an = c.checked;
  const body = c.dataset.wiederholung
    ? { wiederholung: c.dataset.wiederholung, erledigt: an }
    : { projekt: c.dataset.projekt, thema_id: c.dataset.thema, von: Number(c.dataset.von), bis: Number(c.dataset.bisGespeichert ?? c.dataset.bis), erledigt: an };
  const zeile = c.closest('li,.lp-wdh-zeile');
  if (zeile) zeile.classList.toggle('erledigt', an);
  ziel.querySelectorAll('input[type=checkbox]').forEach((x) => { x.disabled = true; });
  try {
    zeichnePlan(await H.api('PUT', `/lernplaene/${encodeURIComponent(p.id)}/erledigt`, body), ziel);
  } catch (e) {
    ziel.querySelectorAll('input[type=checkbox]').forEach((x) => { x.disabled = false; });
    c.checked = !an;
    if (zeile) zeile.classList.toggle('erledigt', !an);
    H.toast(e.message, true);
  }
}

async function neuVerteilen(p, ziel, knopf) {
  const ok = await H.frage('Plan neu verteilen?', '<p>Alles, was noch nicht erledigt ist, wird neu auf die verbleibenden Lerntage verteilt. Erledigtes bleibt, wie es ist.</p>', 'Neu verteilen');
  if (!ok) return;
  knopf.disabled = true;
  try {
    zeichnePlan(await H.api('POST', `/lernplaene/${encodeURIComponent(p.id)}/neu_verteilen`), ziel);
    H.toast('Plan neu verteilt');
  } catch (e) { knopf.disabled = false; H.toast(e.message, true); }
}

/* ---------------- Start ---------------- */
export function start(hooks) {
  H = hooks;
  if (!document.querySelector('link[data-lernplan]')) {
    const l = document.createElement('link');
    l.rel = 'stylesheet'; l.href = '/ui/funktionen/lernplan.css'; l.dataset.lernplan = '1';
    document.head.appendChild(l);
  }
  H.menue({ text: 'Lernplan', href: '#/lernplan' });
  H.route('lernplan', async (teile, ziel) => {
    if (teile[0]) await seitePlan(decodeURIComponent(teile[0]), ziel);
    else await seiteLernplaene(ziel);
  });
}
