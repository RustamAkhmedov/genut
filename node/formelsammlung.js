// Setzt eine Formelsammlung als PDF (A4 hochkant, zwei Spalten, nur Schwarz/Weiß/Grau).
// Aufruf: node formelsammlung.js <eingabe.json> <ausgabe.pdf>
// Eingabe und Ergebnis: specs/003-formelsammlung/data-model.md. Formeln setzt MathJax als SVG
// (fontCache 'none', jede Formel enthält ihre Pfade selbst), svg-to-pdfkit zeichnet sie als Vektor.
// Das PDF entsteht zuerst als <ausgabe>.tmp und wird erst bei Erfolg umbenannt.
// Ergebnis auf stdout: {ok, seiten, formeln, fehler: [{id, titel, meldung}]}. Exit 1 nur bei Gesamtfehler.
const fs = require('fs');
const path = require('path');
const PDFDocument = require('pdfkit');
const SVGtoPDF = require('svg-to-pdfkit');
const {mathjax} = require('mathjax-full/js/mathjax.js');
const {TeX} = require('mathjax-full/js/input/tex.js');
const {SVG} = require('mathjax-full/js/output/svg.js');
const {liteAdaptor} = require('mathjax-full/js/adaptors/liteAdaptor.js');
const {RegisterHTMLHandler} = require('mathjax-full/js/handlers/html.js');
const {AllPackages} = require('mathjax-full/js/input/tex/AllPackages.js');
const texSicher = require('../ui/tex_sicher.js');

// ---------------------------------------------------------------------------------------------
// Maße (PDF-Punkte, 1 mm = 72/25,4 pt)
const MM = 72 / 25.4;
const SEITE_B = 595.28, SEITE_H = 841.89;
const RAND = 15 * MM;
const SPALTEN_ABSTAND = 8 * MM;
const INHALT_B = SEITE_B - 2 * RAND;
const SPALTE_B = (INHALT_B - SPALTEN_ABSTAND) / 2;
const OBEN = RAND, UNTEN = SEITE_H - RAND;

const GROESSE = {
  formel: 10,        // Basis der Formeln: 1 em = 10 pt, 1 ex = 5 pt
  text: 9,           // Formeltitel
  zusatz: 8.5,       // Variablenliste und Erklärtext (auch Formeln darin)
  thema: 11,
  titel: 16,
  datum: 9,
  rand: 7.5,         // Kopf- und Fußzeile
};
const ABSTAND = {
  nachTitelzeile: 14,
  vorThema: 6,       // nur wenn das Thema nicht oben in der Spalte beginnt
  nachThema: 7,
  titelZuFormel: 4,
  vorZusatz: 5,          // Formel → Variablenliste bzw. → Erklärtext
  zwischenVariablen: 1.5,
  zwischenAbsaetzen: 3.5,
  zwischenPunkten: 1.5,
  umAbgesetzte: 3,       // über und unter abgesetzten Formeln im Erklärtext
  nachBlock: 10,
};
const FARBE = {schwarz: '#000000', grau: '#555555', linie: '#999999'};

const SCHRIFTEN = path.join(__dirname, '..', 'genut', 'render', 'assets', 'fonts');
const SCHRIFT = {
  normal: path.join(SCHRIFTEN, 'DejaVuSans.ttf'),
  fett: path.join(SCHRIFTEN, 'DejaVuSans-Bold.ttf'),
  kursiv: path.join(SCHRIFTEN, 'DejaVuSans-Oblique.ttf'),
  mono: path.join(SCHRIFTEN, 'DejaVuSansMono.ttf'),
};

// ---------------------------------------------------------------------------------------------
// Hilfen

function schriftenAnmelden(doc) {
  doc.registerFont('DejaVu', SCHRIFT.normal);
  doc.registerFont('DejaVu-Bold', SCHRIFT.fett);
  doc.registerFont('DejaVu-Italic', SCHRIFT.kursiv);
  doc.registerFont('DejaVu-Mono', SCHRIFT.mono);
  doc.font('DejaVu');
}

function text(wert) {
  return wert == null ? '' : String(wert);
}

// Jede Farbe auf Grau abbilden (Luminanz), damit auch \color{…} im TeX keine Farbe ins PDF bringt.
function grau(farbe) {
  if (!farbe || !Array.isArray(farbe[0])) return farbe;
  const [r, g, b] = farbe[0];
  const l = Math.round(0.299 * r + 0.587 * g + 0.114 * b);
  return [[l, l, l], farbe[1]];
}

// Schriften für <text>-Elemente im MathJax-SVG (Zeichen, die MathJax nicht als Pfad kennt, z. B. ä).
function svgSchrift(familie, fett, kursiv) {
  if (/mono/i.test(familie || '')) return 'DejaVu-Mono';
  if (fett) return 'DejaVu-Bold';
  if (kursiv) return 'DejaVu-Italic';
  return 'DejaVu';
}

// ---------------------------------------------------------------------------------------------
// Formeln setzen (TeX → SVG → Maße in pt)

const adaptor = liteAdaptor();
RegisterHTMLHandler(adaptor);
const texEingabe = new TeX({
  // noundefined/noerrors würden Fehler rot bzw. als Quelltext setzen statt zu melden.
  packages: AllPackages.filter(p => !['bussproofs', 'physics', 'noundefined', 'noerrors'].includes(p)),
  formatError: (jax, err) => { throw err; },
});
texEingabe.postFilters.add(texSicher);
const mjDok = mathjax.document('', {InputJax: texEingabe, OutputJax: new SVG({fontCache: 'none'})});

class FormelFehler extends Error {}

// Länge aus MathJax („2.5ex“, „1.2em“, „-0.3ex“) in pt bei Schriftgröße `groesse`.
function laenge(wert, groesse) {
  const m = /^\s*(-?[\d.]+)\s*(ex|em)?\s*$/.exec(wert || '');
  if (!m) return null;
  const zahl = parseFloat(m[1]);
  return m[2] === 'em' ? zahl * groesse : zahl * 0.5 * groesse;
}

// Setzt `tex` und liefert {svg, breite, hoehe, tiefe} in pt (tiefe = Teil unter der Grundlinie).
// display: abgesetzt (true) oder im Text (false, Variablenliste und Erklärtext).
function setzeFormel(tex, display = true, groesse = GROESSE.formel) {
  if (!text(tex).trim()) throw new FormelFehler('Die Formel ist leer.');
  let knoten;
  try {
    knoten = mjDok.convert(text(tex), {display, em: 16, ex: 8, containerWidth: 80 * 16});
  } catch (e) {
    throw new FormelFehler('TeX-Fehler: ' + (e && e.message ? e.message : String(e)));
  }
  const svgEl = adaptor.firstChild(knoten);
  if (!svgEl || adaptor.kind(svgEl) !== 'svg') throw new FormelFehler('MathJax hat kein SVG geliefert.');
  const stil = adaptor.getAttribute(svgEl, 'style') || '';
  const breite = laenge(adaptor.getAttribute(svgEl, 'width'), groesse);
  const hoehe = laenge(adaptor.getAttribute(svgEl, 'height'), groesse);
  if (!adaptor.getAttribute(svgEl, 'viewBox') || breite == null || hoehe == null) {
    // z. B. Gleichungsnummern (\tag): MathJax liefert dann Breite 100 % ohne viewBox.
    throw new FormelFehler('Die Formel lässt sich nicht als Vektor setzen (Gleichungsnummer oder Breite unbekannt).');
  }
  const va = /vertical-align:\s*(-?[\d.]+ex)/.exec(stil);
  const tiefe = va ? -laenge(va[1], groesse) : 0;
  // Maße fest in pt eintragen (assumePt), currentColor → Schwarz.
  adaptor.setAttribute(svgEl, 'width', breite.toFixed(3));
  adaptor.setAttribute(svgEl, 'height', hoehe.toFixed(3));
  adaptor.removeAttribute(svgEl, 'style');
  const svg = adaptor.outerHTML(svgEl).replace(/currentColor/g, '#000000');
  return {svg, breite, hoehe, tiefe};
}

// Zeichnet ein gesetztes SVG an (x, y = Oberkante) mit Faktor `skala`.
function zeichneSvg(doc, formel, x, y, skala = 1) {
  const warnungen = [];
  SVGtoPDF(doc, formel.svg, x, y, {
    width: formel.breite * skala,
    height: formel.hoehe * skala,
    assumePt: true,
    preserveAspectRatio: 'xMinYMin meet',
    colorCallback: grau,
    fontCallback: svgSchrift,
    warningCallback: w => warnungen.push(String(w)),
  });
  return warnungen;
}

// Probezeichnung in einem Wegwerf-Dokument: wirft svg-to-pdfkit oder entsteht keine Füllung/Linie,
// gilt die Formel als nicht setzbar. So landet nie eine halbe Formel im eigentlichen PDF.
function neueProbe() {
  const doc = new PDFDocument({autoFirstPage: true, size: [SEITE_B, SEITE_H], margin: 0});
  doc.on('data', () => {});
  schriftenAnmelden(doc);
  let inhalt = [];
  const original = doc.addContent.bind(doc);
  doc.addContent = (daten) => { inhalt.push(String(daten)); return original(daten); };
  let n = 0;
  return (formel) => {
    if (++n % 50 === 0) doc.addPage();
    inhalt = [];
    try {
      zeichneSvg(doc, formel, 0, 0, 1);
    } catch (e) {
      throw new FormelFehler('Die Formel konnte nicht gezeichnet werden: ' + (e && e.message ? e.message : String(e)));
    }
    const ops = inhalt.join('\n');
    if (!/(^|\s)(f\*?|F|S|s|B\*?|b\*?|Tj|TJ)(\s|$)/.test(ops)) {
      throw new FormelFehler('Die Formel konnte nicht gezeichnet werden (leere Zeichnung).');
    }
  };
}

// ---------------------------------------------------------------------------------------------
// Blöcke: ein Block ist eine Liste von Teilen {hoehe, vor, trennbar, zeichne(doc, x, y)} mit fester
// Breite SPALTE_B. `vor` ist der Abstand über dem Teil (entfällt oben in einer Spalte). Ein Block
// bleibt ganz, solange er in eine Spalte passt. Nur ein Block, der höher als eine ganze Spalte ist,
// wird geteilt: bevorzugt vor Teilen mit `trennbar` (Absatz- und Variablengrenzen), notfalls
// zwischen Zeilen (Fluss.langerBlock).

const STIL = {
  text: {schrift: 'DejaVu'},
  fett: {schrift: 'DejaVu-Bold'},
  kursiv: {schrift: 'DejaVu-Italic'},
  code: {schrift: 'DejaVu-Mono', faktor: 0.94},
  grau: {schrift: 'DejaVu', farbe: FARBE.grau},
};
const LEERRAUM = /[ \t\r\n\f\v]+/;            // kein \s: das geschützte Leerzeichen (U+00A0) bindet
const PUNKT_EINZUG = 10;                      // Einzug der Aufzählungspunkte
const HAENGEND_MAX = 0.4;                     // Variablen: Einzug bis zur Bedeutung höchstens 40 % der Spalte
const HAENGEND_ERSATZ = 12;                   // sonst fester hängender Einzug

function stil(name) {
  return STIL[name] || STIL.text;
}

function hoeheVon(teile) {
  return teile.reduce((s, t, i) => s + t.hoehe + (i > 0 ? (t.vor || 0) : 0), 0);
}

// Höhe, die mit dem Anfang des Blocks zusammenbleiben muss (für die Themenüberschrift).
function kopfHoehe(teile, spaltenHoehe) {
  const h = hoeheVon(teile);
  if (h <= spaltenHoehe) return h;
  const ende = teile.findIndex((t, i) => i > 0 && t.trennbar);
  return hoeheVon(ende < 0 ? teile : teile.slice(0, ende));
}

// Setzt Formeln der Zusätze (Variablen, Erklärtext) mit Zwischenspeicher und Probezeichnung und
// sammelt Meldungen für nicht setzbare Formeln (die dann als TeX-Quelltext im PDF stehen).
class Setzer {
  constructor(doc, probe, fehler) {
    this.doc = doc;
    this.probe = probe;
    this.fehler = fehler;
    this.speicher = new Map();
  }

  formel(tex, display, groesse) {
    const schluessel = `${display ? 'D' : 'T'}|${groesse}|${tex}`;
    if (!this.speicher.has(schluessel)) {
      try {
        const formel = setzeFormel(tex, display, groesse);
        this.probe(formel);
        this.speicher.set(schluessel, {formel});
      } catch (e) {
        if (!(e instanceof FormelFehler)) throw e;
        this.speicher.set(schluessel, {fehler: e});
      }
    }
    const t = this.speicher.get(schluessel);
    if (t.fehler) throw t.fehler;
    return t.formel;
  }

  melden(f, ort, tex, e) {
    const name = text(f.titel).trim() || text(f.id) || 'Formel';
    const quelle = tex.length > 60 ? tex.slice(0, 57) + '…' : tex;
    this.fehler.push({
      id: text(f.id), titel: text(f.titel),
      meldung: `„${name}“, ${ort}: „${quelle}“ ließ sich nicht setzen und steht als TeX-Quelltext im PDF (${e.message})`,
    });
  }
}

// Kästchen einer Zeile: Text, Leerraum oder Formel; auf/ab = Höhe über/Tiefe unter der Grundlinie.
function fontMasse(doc, schrift, groesse) {
  doc.font(schrift).fontSize(groesse);
  return {auf: doc._font.ascender / 1000 * groesse, ab: -doc._font.descender / 1000 * groesse};
}

function textKasten(doc, s, st, groesse) {
  const m = fontMasse(doc, st.schrift, groesse);
  return {art: 'text', s, schrift: st.schrift, groesse, farbe: st.farbe || FARBE.schwarz,
    breite: doc.widthOfString(s), auf: m.auf, ab: m.ab};
}

function raumKasten(doc, st, groesse) {
  const k = textKasten(doc, ' ', st, groesse);
  k.art = 'raum';
  k.s = ' ';
  return k;
}

function formelKasten(formel, skala = 1) {
  return {art: 'formel', formel, skala, breite: formel.breite * skala,
    auf: (formel.hoehe - formel.tiefe) * skala, ab: formel.tiefe * skala};
}

// Textstücke → Wörter (Folgen von Kästchen ohne Umbruchstelle), je mit dem Leerraum davor.
// Ein Wort darf Text und Formeln mischen („(\(x\))“ bleibt zusammen).
function woerterAus(setzer, f, stuecke, groesse, ort) {
  const doc = setzer.doc;
  const woerter = [];
  let wort = null, raum = null;
  const kasten = (k) => {
    if (!wort) {
      wort = {raum, kaesten: []};
      woerter.push(wort);
      raum = null;
    }
    wort.kaesten.push(k);
  };
  const luecke = (r) => {
    if (wort) {
      wort = null;
      raum = r;
    } else if (woerter.length && !raum) {
      raum = r;
    }
  };
  const textStueck = (s, stilName) => {
    const st = stil(stilName);
    const gr = groesse * (st.faktor || 1);
    for (const teil of s.split(new RegExp(`(${LEERRAUM.source})`))) {
      if (!teil) continue;
      if (LEERRAUM.test(teil) && !teil.replace(LEERRAUM, '')) luecke(raumKasten(doc, st, gr));
      else kasten(textKasten(doc, teil, st, gr));
    }
  };
  for (const st of stuecke) {
    if (!st || typeof st !== 'object') continue;
    const s = text(st.s);
    if (st.t === 'formel' || st.t === 'formel_block') {
      // formel_block kommt hier nur an, wenn es im Fließtext steht (siehe absatzTeile); dann wie im Text.
      if (!s.trim()) continue;
      try {
        kasten(formelKasten(setzer.formel(s, false, groesse)));
      } catch (e) {
        setzer.melden(f, ort, s, e);
        textStueck(s, 'code');
      }
    } else {
      textStueck(s, st.t);
    }
  }
  return woerter;
}

// Teilt ein Textkästchen so, dass der vordere Teil höchstens `rest` breit ist (harter Umbruch).
function textTeilen(doc, k, rest) {
  const zeichen = Array.from(k.s);
  const st = {schrift: k.schrift, farbe: k.farbe};
  doc.font(k.schrift).fontSize(k.groesse);
  let lo = 0, hi = zeichen.length - 1;     // größtes n mit Breite(zeichen[0..n)) <= rest
  while (lo < hi) {
    const mitte = Math.ceil((lo + hi) / 2);
    if (doc.widthOfString(zeichen.slice(0, mitte).join('')) <= rest) lo = mitte;
    else hi = mitte - 1;
  }
  if (lo === 0) return [null, k];
  return [textKasten(doc, zeichen.slice(0, lo).join(''), st, k.groesse),
    textKasten(doc, zeichen.slice(lo).join(''), st, k.groesse)];
}

// Greedy-Zeilenumbruch. breiteVon(i) = verfügbare Breite der Zeile i. Liefert Listen von Kästchen.
function umbrechen(doc, woerter, breiteVon) {
  const zeilen = [];
  let z;
  const neu = () => {
    z = {kaesten: [], x: 0};
    zeilen.push(z);
  };
  const setze = (k) => {
    z.kaesten.push(k);
    z.x += k.breite;
  };
  const W = () => breiteVon(zeilen.length - 1);
  const minW = Math.min(breiteVon(0), breiteVon(1));
  neu();
  for (const wort of woerter) {
    // Formeln, die breiter als jede Zeile sind, verkleinern.
    const kaesten = wort.kaesten.map(k => (k.art === 'formel' && k.breite > minW)
      ? formelKasten(k.formel, k.skala * minW / k.breite) : k);
    const wb = kaesten.reduce((s, k) => s + k.breite, 0);
    const voll = z.kaesten.length > 0;
    const rb = voll && wort.raum ? wort.raum.breite : 0;
    if (voll && z.x + rb + wb <= W() + 0.01) {
      if (rb) setze(wort.raum);
      kaesten.forEach(setze);
      continue;
    }
    if (wb <= breiteVon(voll ? zeilen.length : zeilen.length - 1) + 0.01) {
      if (voll) neu();
      kaesten.forEach(setze);
      continue;
    }
    // Wort länger als eine ganze Zeile: hart umbrechen, angefangene Zeile möglichst auffüllen.
    if (voll) {
      if (W() - z.x - rb >= 0.25 * W()) {
        if (rb) setze(wort.raum);
      } else {
        neu();
      }
    }
    for (const k0 of kaesten) {
      let k = k0;
      while (k) {
        const rest = W() - z.x;
        if (k.breite <= rest + 0.01) {
          setze(k);
          break;
        }
        if (k.art !== 'text') {      // Formel passt nicht mehr: neue Zeile (sie ist höchstens minW breit)
          if (z.kaesten.length) { neu(); continue; }
          setze(k);
          break;
        }
        let [vorne, hinten] = textTeilen(doc, k, rest);
        if (!vorne) {
          if (z.kaesten.length) { neu(); continue; }
          const zeichen = Array.from(k.s);  // nicht einmal ein Zeichen passt: trotzdem eins setzen
          const st = {schrift: k.schrift, farbe: k.farbe};
          vorne = textKasten(doc, zeichen[0], st, k.groesse);
          hinten = zeichen.length > 1 ? textKasten(doc, zeichen.slice(1).join(''), st, k.groesse) : null;
        }
        setze(vorne);
        if (!hinten) break;
        neu();
        k = hinten;
      }
    }
  }
  return zeilen.filter(zl => zl.kaesten.length);
}

// Zeichnet die Kästchen einer Zeile ab x auf der Grundlinie `grund`. Benachbarter Text gleicher
// Schrift wird als ein Lauf gesetzt (sauberer Text beim Kopieren und Durchsuchen).
function zeichneZeile(d, kaesten, x0, grund) {
  let x = x0, lauf = null;
  const ausgeben = () => {
    if (!lauf) return;
    d.font(lauf.schrift).fontSize(lauf.groesse).fillColor(lauf.farbe)
      .text(lauf.s, lauf.x, grund, {lineBreak: false, baseline: 'alphabetic'});
    lauf = null;
  };
  for (const k of kaesten) {
    if (k.art === 'formel') {
      ausgeben();
      zeichneSvg(d, k.formel, x, grund - k.auf, k.skala);
    } else if (lauf && lauf.schrift === k.schrift && lauf.groesse === k.groesse && lauf.farbe === k.farbe) {
      lauf.s += k.s;
    } else {
      ausgeben();
      if (k.art === 'text') lauf = {s: k.s, x, schrift: k.schrift, groesse: k.groesse, farbe: k.farbe};
    }
    x += k.breite;
  }
  ausgeben();
}

// Wörter → Zeilen-Teile. opt: groesse (Mindest-Zeilenmaß), einzugVon(i), breiteVon(i), vor (erste
// Zeile), trennbar (erste Zeile), punkt (Aufzählungszeichen vor der ersten Zeile), mitte (zentrieren).
const ZEILEN_ABSTAND = 1.5;
function zeilenTeile(doc, woerter, opt) {
  const {groesse, einzugVon = () => 0, breiteVon = () => SPALTE_B, vor = 0, trennbar = false, punkt = false} = opt;
  const strut = fontMasse(doc, STIL.text.schrift, groesse);
  return umbrechen(doc, woerter, breiteVon).map((zl, i) => {
    const auf = Math.max(strut.auf, ...zl.kaesten.map(k => k.auf));
    const ab = Math.max(strut.ab, ...zl.kaesten.map(k => k.ab));
    const einzug = einzugVon(i);
    return {
      hoehe: auf + ab,
      vor: i === 0 ? vor : ZEILEN_ABSTAND,
      trennbar: i === 0 && trennbar,
      zeichne(d, x, y) {
        if (punkt && i === 0) {
          d.font(STIL.text.schrift).fontSize(groesse).fillColor(FARBE.schwarz)
            .text('•', x + 2, y + auf, {lineBreak: false, baseline: 'alphabetic'});
        }
        zeichneZeile(d, zl.kaesten, x + einzug, y + auf);
      },
    };
  });
}

// Formeltitel (fett), dahinter grau das Kennzeichen („(nicht bestätigt)“, „(ungeprüft)“).
function teileTitel(setzer, f) {
  const titel = text(f.titel).trim();
  const kennzeichen = text(f.kennzeichen).trim().replace(/^\((.*)\)$/, '$1').trim();
  const stuecke = [];
  if (titel) stuecke.push({t: 'fett', s: titel});
  if (kennzeichen) stuecke.push({t: 'grau', s: `${titel ? ' ' : ''}(${kennzeichen.replace(/ /g, ' ')})`});
  if (!stuecke.length) return [];
  return zeilenTeile(setzer.doc, woerterAus(setzer, f, stuecke, GROESSE.text, 'Titel'), {groesse: GROESSE.text});
}

// Abgesetzte Formel, mittig in der Breite `breite` ab `einzug`, auf Breite und `maxHoehe` verkleinert.
function teilFormel(formel, maxHoehe, {breite = SPALTE_B, einzug = 0, vor = 0, trennbar = false} = {}) {
  let skala = Math.min(1, breite / formel.breite);
  if (formel.hoehe * skala > maxHoehe) skala = maxHoehe / formel.hoehe;
  const b = formel.breite * skala, h = formel.hoehe * skala;
  return {
    hoehe: h,
    vor,
    trennbar,
    zeichne(d, x, y) {
      zeichneSvg(d, formel, x + einzug + (breite - b) / 2, y, skala);
    },
  };
}

// Bedeutung einer Variable: Text (mit \(…\) oder $…$ als Formel) oder schon eine Liste von Stücken.
const INLINE_TEX = /\\\((.+?)\\\)|\$(?=\S)([^$\n]*?\S)\$/g;
function bedeutungStuecke(wert) {
  if (Array.isArray(wert)) return wert;
  const s = text(wert);
  const stuecke = [];
  let pos = 0;
  for (const m of s.matchAll(INLINE_TEX)) {
    stuecke.push({t: 'text', s: s.slice(pos, m.index)});
    stuecke.push({t: 'formel', s: (m[1] != null ? m[1] : m[2]).trim()});
    pos = m.index + m[0].length;
  }
  stuecke.push({t: 'text', s: s.slice(pos)});
  return stuecke;
}

// Variablenliste: „Name – Bedeutung“, Folgezeilen hängend bis zum Beginn der Bedeutung eingerückt.
function teileVariablen(setzer, f) {
  const doc = setzer.doc;
  const gr = GROESSE.zusatz;
  const teile = [];
  const liste = Array.isArray(f.variablen) ? f.variablen : [];
  for (const v of liste) {
    if (!v || typeof v !== 'object') continue;
    const name = text(v.tex != null ? v.tex : v.name).trim();
    const bedeutung = bedeutungStuecke(v.text != null ? v.text : v.bedeutung);
    const kopf = woerterAus(setzer, f, name ? [{t: 'formel', s: name}] : [], gr, 'Variablenliste');
    const rest = woerterAus(setzer, f, bedeutung, gr, 'Variablenliste');
    if (!kopf.length && !rest.length) continue;
    let woerter = rest, einzug = 0;
    if (kopf.length) {
      // Name, geschütztes Leerzeichen und Gedankenstrich bilden ein Wort (der Strich beginnt nie eine Zeile).
      const raum = raumKasten(doc, STIL.text, gr);
      const strich = textKasten(doc, '–', STIL.text, gr);
      const name = kopf.flatMap((w, i) => (i ? [w.raum || raum] : []).concat(w.kaesten));
      const erstes = {raum: null, kaesten: rest.length ? [...name, raum, strich] : name};
      if (rest.length) rest[0] = {...rest[0], raum};
      woerter = [erstes, ...rest];
      einzug = erstes.kaesten.reduce((s, k) => s + k.breite, 0) + raum.breite;
      if (einzug > HAENGEND_MAX * SPALTE_B) einzug = HAENGEND_ERSATZ;
    } else {
      einzug = HAENGEND_ERSATZ;
    }
    teile.push(...zeilenTeile(doc, woerter, {
      groesse: gr,
      einzugVon: i => (i === 0 ? 0 : einzug),
      breiteVon: i => (i === 0 ? SPALTE_B : SPALTE_B - einzug),
      vor: teile.length ? ABSTAND.zwischenVariablen : ABSTAND.vorZusatz,
      trennbar: true,
    }));
  }
  return teile;
}

// Ein Absatz der Eingabe → {punkt, stuecke}. Erwartet: Liste von Stücken, erstes Stück ggf. mit
// "punkt": true. Toleriert auch {punkt, stuecke: […]}, ein einzelnes Stück oder einen Text.
function absatzLesen(a) {
  if (typeof a === 'string') return {punkt: false, stuecke: [{t: 'text', s: a}]};
  if (Array.isArray(a)) {
    const stuecke = a.filter(st => st && typeof st === 'object');
    return {punkt: stuecke.length > 0 && stuecke[0].punkt === true, stuecke};
  }
  if (a && typeof a === 'object') {
    if (Array.isArray(a.stuecke)) {
      const inner = absatzLesen(a.stuecke);
      return {punkt: a.punkt === true || inner.punkt, stuecke: inner.stuecke};
    }
    if ('t' in a || 's' in a) return {punkt: a.punkt === true, stuecke: [a]};
  }
  return null;
}

function absaetzeLesen(erklaerung) {
  if (typeof erklaerung === 'string') {
    return erklaerung.split(/\n\s*\n/).filter(s => s.trim()).map(absatzLesen);
  }
  return (Array.isArray(erklaerung) ? erklaerung : []).map(absatzLesen)
    .filter(a => a && a.stuecke.some(st => text(st.s).trim()));
}

// Erklärtext: Absätze mit Wörtern und Formeln im Fließtext, abgesetzte Formeln zentriert,
// Aufzählungspunkte mit Einzug.
function teileErklaerung(setzer, f, spaltenHoehe) {
  const doc = setzer.doc;
  const gr = GROESSE.zusatz;
  const teile = [];
  let vorher = null;      // war der vorige Absatz ein Aufzählungspunkt?
  for (const absatz of absaetzeLesen(f.erklaerung)) {
    const einzug = absatz.punkt ? PUNKT_EINZUG : 0;
    const breite = SPALTE_B - einzug;
    const vor = !teile.length ? ABSTAND.vorZusatz
      : (absatz.punkt && vorher ? ABSTAND.zwischenPunkten : ABSTAND.zwischenAbsaetzen);
    let erstes = true;
    let punkt = absatz.punkt;
    // Absatz an abgesetzten Formeln in Abschnitte teilen.
    const abschnitte = [];
    for (const st of absatz.stuecke) {
      if (st.t === 'formel_block') abschnitte.push({block: text(st.s)});
      else if (abschnitte.length && Array.isArray(abschnitte[abschnitte.length - 1])) abschnitte[abschnitte.length - 1].push(st);
      else abschnitte.push([st]);
    }
    for (const ab of abschnitte) {
      let neu = [];
      if (Array.isArray(ab)) {
        const woerter = woerterAus(setzer, f, ab, gr, 'Erklärtext');
        if (!woerter.length) continue;
        neu = zeilenTeile(doc, woerter, {groesse: gr, einzugVon: () => einzug, breiteVon: () => breite,
          vor: erstes ? vor : ABSTAND.umAbgesetzte, trennbar: erstes, punkt});
      } else {
        if (!ab.block.trim()) continue;
        try {
          const formel = setzer.formel(ab.block, true, gr);
          neu = [teilFormel(formel, spaltenHoehe, {breite, einzug, vor: erstes ? vor : ABSTAND.umAbgesetzte, trennbar: erstes})];
          if (punkt) {
            const t = neu[0];
            const zeichne = t.zeichne;
            t.zeichne = (d, x, y) => {
              d.font(STIL.text.schrift).fontSize(gr).fillColor(FARBE.schwarz)
                .text('•', x + 2, y + Math.min(t.hoehe / 2, gr), {lineBreak: false, baseline: 'middle'});
              zeichne(d, x, y);
            };
          }
        } catch (e) {
          if (!(e instanceof FormelFehler)) throw e;
          setzer.melden(f, 'Erklärtext', ab.block, e);
          const woerter = woerterAus(setzer, f, [{t: 'code', s: ab.block}], gr, 'Erklärtext');
          neu = zeilenTeile(doc, woerter, {groesse: gr, einzugVon: () => einzug, breiteVon: () => breite,
            vor: erstes ? vor : ABSTAND.umAbgesetzte, trennbar: erstes, punkt});
        }
      }
      if (!neu.length) continue;
      teile.push(...neu);
      erstes = false;
      punkt = false;
    }
    if (!erstes) vorher = absatz.punkt;
  }
  return teile;
}

function formelBlock(setzer, f, formel, spaltenHoehe) {
  const teile = teileTitel(setzer, f);
  const rest = hoeheVon(teile) + (teile.length ? ABSTAND.titelZuFormel : 0);
  teile.push(teilFormel(formel, Math.max(20, spaltenHoehe - rest), {vor: teile.length ? ABSTAND.titelZuFormel : 0}));
  teile.push(...teileVariablen(setzer, f));
  teile.push(...teileErklaerung(setzer, f, spaltenHoehe));
  return teile;
}

// ---------------------------------------------------------------------------------------------
// Seitenfluss

class Fluss {
  constructor(doc) {
    this.doc = doc;
    this.seiten = [];          // je Seite: Oberkante der Spalten (für die Trennlinie)
    this.nachThema = false;    // steht direkt über der Position eine Themenüberschrift?
    this.neueSeite(true);
  }

  neueSeite(erste = false) {
    if (!erste) this.doc.addPage();
    this.spalte = 0;
    this.oben = OBEN;
    this.y = OBEN;
    this.seiten.push({oben: OBEN, benutzt: [false, false]});
  }

  // Erste Seite: Titelzeile über beide Spalten.
  titelzeile(titel, datum) {
    const d = this.doc;
    d.font('DejaVu-Bold').fontSize(GROESSE.titel);
    const datumB = (() => { d.font('DejaVu').fontSize(GROESSE.datum); return d.widthOfString(datum); })();
    d.font('DejaVu-Bold').fontSize(GROESSE.titel);
    const titelB = INHALT_B - datumB - 12;
    const h = d.heightOfString(titel, {width: titelB});
    d.fillColor(FARBE.schwarz).text(titel, RAND, OBEN, {width: titelB});
    d.font('DejaVu').fontSize(GROESSE.datum).fillColor(FARBE.grau)
      .text(datum, RAND + INHALT_B - datumB, OBEN + h - GROESSE.datum * 1.25, {width: datumB + 1, lineBreak: false});
    const linieY = OBEN + h + 3;
    d.save().lineWidth(0.8).strokeColor(FARBE.schwarz)
      .moveTo(RAND, linieY).lineTo(RAND + INHALT_B, linieY).stroke().restore();
    this.oben = linieY + ABSTAND.nachTitelzeile;
    this.y = this.oben;
    this.seiten[0].oben = this.oben;
  }

  get x() {
    return RAND + this.spalte * (SPALTE_B + SPALTEN_ABSTAND);
  }

  // Kleinste Spaltenhöhe (Seite 1 unter der Titelzeile): so passt ein Block in jede leere Spalte.
  get spaltenHoehe() {
    return UNTEN - this.seiten[0].oben;
  }

  leer() {
    return this.y <= this.oben + 0.01;
  }

  naechsteSpalte() {
    if (this.spalte === 0) {
      this.spalte = 1;
      this.y = this.oben;
    } else {
      this.neueSeite();
    }
  }

  // Sorgt dafür, dass `h` pt in die aktuelle Spalte passen (sonst nächste Spalte/Seite).
  platz(h) {
    if (this.y + h > UNTEN && !this.leer()) this.naechsteSpalte();
  }

  markieren() {
    this.seiten[this.seiten.length - 1].benutzt[this.spalte] = true;
  }

  // `vor` gilt nicht für den ersten Teil (außer mitVor) und nie oben in einer Spalte.
  zeichneTeile(teile, mitVor = false) {
    teile.forEach((t, i) => {
      if ((i > 0 || mitVor) && !this.leer()) this.y += t.vor || 0;
      t.zeichne(this.doc, this.x, this.y);
      this.y += t.hoehe;
    });
    this.markieren();
  }

  // Themenüberschrift (fett, Linie darunter). `folgeHoehe` hält sie mit dem ersten Block zusammen.
  thema(titel, folgeHoehe) {
    const d = this.doc;
    d.font('DejaVu-Bold').fontSize(GROESSE.thema);
    const opt = {width: SPALTE_B, lineGap: 1};
    const textH = d.heightOfString(titel, opt);
    const h = textH + 3 + ABSTAND.nachThema;
    const vor = this.leer() ? 0 : ABSTAND.vorThema;
    if (this.y + vor + h + folgeHoehe > UNTEN && !this.leer()) this.naechsteSpalte();
    if (!this.leer()) this.y += ABSTAND.vorThema;
    d.font('DejaVu-Bold').fontSize(GROESSE.thema).fillColor(FARBE.schwarz).text(titel, this.x, this.y, opt);
    const linieY = this.y + textH + 1.5;
    d.save().lineWidth(0.8).strokeColor(FARBE.schwarz)
      .moveTo(this.x, linieY).lineTo(this.x + SPALTE_B, linieY).stroke().restore();
    this.y += h;
    this.markieren();
    this.nachThema = true;
  }

  // Ein Block bleibt ganz (nächste Spalte oder Seite, wenn er nicht mehr passt).
  block(teile) {
    const h = hoeheVon(teile);
    if (h <= this.spaltenHoehe + 0.01) {
      this.platz(h);
      this.zeichneTeile(teile);
    } else {
      this.langerBlock(teile);
    }
    this.y += ABSTAND.nachBlock;
    this.nachThema = false;
  }

  // Block höher als eine Spalte: oben in einer Spalte beginnen (außer direkt unter der Themen-
  // überschrift) und vor `trennbar`-Teilen umbrechen; eine Gruppe, die allein nicht in eine
  // Spalte passt, wird zeilenweise verteilt. So verschwindet nie etwas und es bleibt bei möglichst
  // wenigen Brüchen.
  langerBlock(teile) {
    if (!this.leer() && !this.nachThema) this.naechsteSpalte();
    const gruppen = [];
    for (const t of teile) {
      if (!gruppen.length || t.trennbar) gruppen.push([]);
      gruppen[gruppen.length - 1].push(t);
    }
    gruppen.forEach((g, gi) => {
      const vor = (gi > 0 && !this.leer()) ? (g[0].vor || 0) : 0;
      // Eine Gruppe, die ohnehin nicht in eine Spalte passt, beginnt sofort (kein leerer Rest).
      const passt = hoeheVon(g) <= this.spaltenHoehe;
      if (passt && this.y + vor + hoeheVon(g) > UNTEN && !this.leer()) this.naechsteSpalte();
      const v = (gi > 0 && !this.leer()) ? (g[0].vor || 0) : 0;
      if (this.y + v + hoeheVon(g) <= UNTEN) {
        this.zeichneTeile(g, gi > 0);
        return;
      }
      g.forEach((t, i) => {
        const tv = ((gi > 0 || i > 0) && !this.leer()) ? (t.vor || 0) : 0;
        if (this.y + tv + t.hoehe > UNTEN && !this.leer()) this.naechsteSpalte();
        this.zeichneTeile([t], gi > 0 || i > 0);
      });
    });
  }

  // Kopf-, Fußzeile und Spaltentrennlinie auf allen Seiten (bufferPages).
  rahmen(kopf) {
    const d = this.doc;
    const bereich = d.bufferedPageRange();
    const gesamt = bereich.count;
    for (let i = 0; i < gesamt; i++) {
      d.switchToPage(bereich.start + i);
      const s = this.seiten[i];
      if (s && s.benutzt[1]) {
        const lx = RAND + SPALTE_B + SPALTEN_ABSTAND / 2;
        d.save().lineWidth(0.4).strokeColor(FARBE.linie)
          .moveTo(lx, s.oben).lineTo(lx, UNTEN).stroke().restore();
      }
      d.font('DejaVu').fontSize(GROESSE.rand).fillColor(FARBE.grau);
      const kopfY = RAND / 2 - GROESSE.rand / 2;
      d.text(kopf, RAND, kopfY, {width: INHALT_B, lineBreak: false, ellipsis: true});
      const fuss = `Seite ${i + 1} von ${gesamt}`;
      const fussY = SEITE_H - RAND / 2 - GROESSE.rand / 2;
      d.text(fuss, RAND, fussY, {width: INHALT_B, align: 'right', lineBreak: false});
    }
  }
}

// ---------------------------------------------------------------------------------------------
// Ablauf

function heute() {
  const d = new Date();
  const z = n => String(n).padStart(2, '0');
  return `${z(d.getDate())}.${z(d.getMonth() + 1)}.${d.getFullYear()}`;
}

function bauen(eingabe, zielPdf) {
  const projekt = text(eingabe.projekt).trim() || 'Projekt';
  const fach = text(eingabe.fach).trim();
  const datum = text(eingabe.datum).trim() || heute();
  const themen = Array.isArray(eingabe.themen) ? eingabe.themen : [];

  const fehler = [];
  // 1. Alle Formeln setzen und probezeichnen, bevor die Seiten entstehen.
  const probe = neueProbe();
  const plan = [];
  for (const thema of themen) {
    const formeln = [];
    for (const f of (thema && Array.isArray(thema.formeln) ? thema.formeln : [])) {
      if (!f || typeof f !== 'object') continue;
      try {
        const formel = setzeFormel(f.tex, true);
        probe(formel);
        formeln.push({f, formel});
      } catch (e) {
        if (!(e instanceof FormelFehler)) throw e;
        fehler.push({id: text(f.id), titel: text(f.titel), meldung: e.message});
      }
    }
    if (formeln.length) plan.push({titel: text(thema.titel).trim(), formeln});
  }

  // 2. Seiten setzen.
  const titel = `Formelsammlung ${projekt}`;
  const doc = new PDFDocument({
    size: [SEITE_B, SEITE_H],
    margin: 0,               // Ränder verwaltet der Fluss selbst (kein automatischer Seitenumbruch)
    bufferPages: true,
    autoFirstPage: true,
    info: {Title: titel, Subject: fach ? `${projekt} · ${fach}` : projekt, Creator: 'gen_Ut'},
  });
  schriftenAnmelden(doc);
  const tmp = zielPdf + '.tmp';
  const strom = fs.createWriteStream(tmp);
  doc.pipe(strom);

  const fluss = new Fluss(doc);
  fluss.titelzeile(titel, datum);
  const setzer = new Setzer(doc, probe, fehler);
  let gesetzt = 0;
  for (const thema of plan) {
    const bloecke = thema.formeln.map(({f, formel}) => formelBlock(setzer, f, formel, fluss.spaltenHoehe));
    if (thema.titel) fluss.thema(thema.titel, kopfHoehe(bloecke[0], fluss.spaltenHoehe));
    for (const teile of bloecke) {
      fluss.block(teile);
      gesetzt++;
    }
  }
  fluss.rahmen(fach ? `${projekt} · ${fach}` : projekt);
  const seiten = doc.bufferedPageRange().count;
  doc.end();

  return new Promise((ok, nein) => {
    strom.on('error', nein);
    doc.on('error', nein);
    strom.on('finish', () => {
      try {
        fs.renameSync(tmp, zielPdf);
        ok({ok: true, seiten, formeln: gesetzt, fehler});
      } catch (e) {
        nein(e);
      }
    });
  });
}

async function main() {
  const [,, einPfad, ausPfad] = process.argv;
  if (!einPfad || !ausPfad) throw new Error('Aufruf: node formelsammlung.js <eingabe.json> <ausgabe.pdf>');
  let eingabe;
  try {
    eingabe = JSON.parse(fs.readFileSync(einPfad, 'utf8'));
  } catch (e) {
    throw new Error('Eingabe nicht lesbar: ' + e.message);
  }
  if (!eingabe || typeof eingabe !== 'object' || Array.isArray(eingabe)) throw new Error('Eingabe ist kein JSON-Objekt.');
  for (const datei of Object.values(SCHRIFT)) {
    if (!fs.existsSync(datei)) throw new Error('Schrift fehlt: ' + datei);
  }
  const ergebnis = await bauen(eingabe, ausPfad);
  process.stdout.write(JSON.stringify(ergebnis) + '\n');
}

main().catch((e) => {
  const ausPfad = process.argv[3];
  if (ausPfad) {
    try { fs.unlinkSync(ausPfad + '.tmp'); } catch (_) { /* nichts da */ }
  }
  process.stderr.write('Formelsammlung: ' + (e && e.message ? e.message : String(e)) + '\n');
  process.exit(1);
});
