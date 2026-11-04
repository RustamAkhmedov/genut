// Ersetzt alle TeX-Stellen (\( \) inline, \[ \] abgesetzt) zwischen <!--MATH-START--> und <!--MATH-END-->
// durch SVG mit gemeinsamem Glyph-Cache. Grundlage: build.js aus der Lern-App-Vorlage.
// Aufruf: node prerender.js <ein.html> <aus.html>
const fs = require('fs');
const path = require('path');
const {mathjax} = require('mathjax-full/js/mathjax.js');
const {TeX} = require('mathjax-full/js/input/tex.js');
const {SVG} = require('mathjax-full/js/output/svg.js');
const {liteAdaptor} = require('mathjax-full/js/adaptors/liteAdaptor.js');
const {RegisterHTMLHandler} = require('mathjax-full/js/handlers/html.js');
const {AllPackages} = require('mathjax-full/js/input/tex/AllPackages.js');

const [,, inPath, outPath] = process.argv;
const src = fs.readFileSync(inPath, 'utf8');
const A = '<!--MATH-START-->', B = '<!--MATH-END-->', STYLE = '<!--MATH-STYLE-->';
const a = src.indexOf(A), b = src.indexOf(B);
if (a < 0 || b < 0) throw new Error('Markierungen fehlen');
const headPart = src.slice(0, a);
const tail = src.slice(b + B.length);

// Lange Inline-Formeln an Trennstellen der obersten Ebene aufteilen, damit der Browser umbrechen kann.
function splitInline(tex, seps) {
  seps = seps || [['\\qquad', 'em'], ['\\quad', 'em'], ['\\Rightarrow', 'next'], [',\\ ', 'prev']];
  let depth = 0, lr = 0, env = 0, cur = '';
  const chunks = [];
  let gap = '';
  for (let i = 0; i < tex.length;) {
    const rest = tex.slice(i);
    let m;
    if ((m = /^\\(left|right)(?![a-zA-Z])/.exec(rest))) { lr += m[1] === 'left' ? 1 : -1; cur += m[0]; i += m[0].length; continue; }
    if ((m = /^\\(begin|end)(?![a-zA-Z])/.exec(rest))) { env += m[1] === 'begin' ? 1 : -1; cur += m[0]; i += m[0].length; continue; }
    if (rest.startsWith('\\{') || rest.startsWith('\\}')) { cur += rest.slice(0, 2); i += 2; continue; }
    const ch = tex[i];
    if (ch === '{') depth++;
    if (ch === '}') depth--;
    if (depth === 0 && lr === 0 && env === 0) {
      let hit = null;
      for (const [sep, mode] of seps) {
        if (rest.startsWith(sep) && !(/[a-zA-Z]$/.test(sep) && /^[a-zA-Z]/.test(rest.slice(sep.length)))) { hit = [sep, mode]; break; }
      }
      if (hit) {
        const [sep, mode] = hit;
        if (mode === 'em') { chunks.push([cur, gap]); cur = ''; gap = ' '; }
        else if (mode === 'next') { chunks.push([cur, gap]); cur = sep; gap = ' '; }
        else { chunks.push([cur + ',', gap]); cur = ''; gap = ' '; }
        i += sep.length;
        continue;
      }
    }
    cur += ch; i++;
  }
  chunks.push([cur, gap]);
  let ok = chunks.filter(c => c[0].trim().length);
  if (!seps.second) {
    const more = [];
    for (const c of ok) {
      const sub = c[0].trim().length > 34 ? splitParts(c[0].trim()) : null;
      if (sub) { sub.forEach((p, k) => more.push([p, k ? ' ' : c[1]])); } else more.push(c);
    }
    ok = more;
  }
  if (ok.length < 2) return null;
  return ok.map((c, k) => (k ? c[1] : '') + '\\(' + c[0].trim() + '\\)').join('');
}
function splitParts(tex) {
  const seps2 = [['\\approx', 'next'], ['=', 'next']];
  seps2.second = true;
  const r = splitInline(tex, seps2);
  if (!r) return null;
  return r.split(/ /).map(x => x.replace(/^\\\(|\\\)$/g, ''));
}
const bodyPart = src.slice(a + A.length, b).replace(/\\\(([\s\S]*?)\\\)/g, (all, tex) => {
  if (tex.length < 28) return all;
  const r = splitInline(tex);
  return r || all;
});

const adaptor = liteAdaptor({fontSize: 17});
RegisterHTMLHandler(adaptor);
let fehler = 0;
const tex = new TeX({
  packages: AllPackages.filter(p => !['bussproofs', 'physics'].includes(p)),
  inlineMath: [['\\(', '\\)']],
  displayMath: [['\\[', '\\]']],
  processEscapes: false,
  formatError: (jax, err) => { fehler++; console.error('TeX-Fehler: ' + err.message); return jax.formatError(err); }
});
const svg = new SVG({fontCache: 'global'});
const doc = mathjax.document(`<!DOCTYPE html><html><head></head><body>${bodyPart}</body></html>`, {InputJax: tex, OutputJax: svg});
doc.render();
const items = Array.from(doc.math);

// Inline-Formeln, die auch nach dem Aufteilen breiter als eine Handyzeile sind (ca. 28ex ≈ 260 px),
// bekommen das Attribut "breit": Das CSS macht sie dann in sich scrollbar statt die Seite zu verbreitern.
const BREIT_EX = 28;
for (const item of items) {
  const root = item.typesetRoot;
  if (!root) continue;
  adaptor.setAttribute(root, 'role', 'img');
  adaptor.setAttribute(root, 'aria-label', item.math.replace(/\s+/g, ' ').trim());
  const svgEl = adaptor.firstChild(root);
  const w = svgEl && parseFloat(adaptor.getAttribute(svgEl, 'width') || '');
  if (!item.display && w > BREIT_EX) adaptor.setAttribute(root, 'breit', '');
}
const DROP = ['data-mml-node', 'data-c', 'data-mjx-texclass', 'data-variant', 'role', 'focusable', 'xmlns', 'xmlns:xlink'];
function clean(node, inSvg) {
  const kind = adaptor.kind(node);
  if (kind === '#text' || kind === '#comment') return;
  const svgHere = inSvg || kind === 'svg';
  if (svgHere && adaptor.getAttribute(node, 'id') !== 'MJX-SVG-global-cache') {
    for (const d of DROP) if (adaptor.hasAttribute(node, d)) adaptor.removeAttribute(node, d);
    const h = adaptor.getAttribute(node, 'xlink:href');
    if (h) { adaptor.removeAttribute(node, 'xlink:href'); adaptor.setAttribute(node, 'href', h); }
    if (kind === 'svg') adaptor.setAttribute(node, 'aria-hidden', 'true');
  }
  for (const c of adaptor.childNodes(node).slice()) clean(c, svgHere);
  if (kind === 'g' && adaptor.allAttributes(node).length === 0) {
    for (const c of adaptor.childNodes(node).slice()) adaptor.insert(c, node);
    adaptor.remove(node);
  }
}
function cleanCache(node) {
  if (adaptor.kind(node) === '#text') return;
  if (adaptor.hasAttribute(node, 'data-c')) adaptor.removeAttribute(node, 'data-c');
  for (const c of adaptor.childNodes(node).slice()) cleanCache(c);
}

const body = adaptor.body(doc.document);
const cache = adaptor.elementById(body, 'MJX-SVG-global-cache');
let cacheHTML = '';
if (cache) {
  for (const n of adaptor.childNodes(cache).slice()) cleanCache(n);
  cacheHTML = adaptor.outerHTML(cache).replace(' xmlns="http://www.w3.org/2000/svg"', '');
  adaptor.remove(cache);
}
clean(body, false);
const bodyHTML = adaptor.innerHTML(body);
const styleNode = svg.svgStyles || adaptor.elementById(adaptor.head(doc.document), 'MJX-SVG-styles');
const styleHTML = styleNode ? adaptor.outerHTML(styleNode) : '';

const head = headPart.includes(STYLE) ? headPart.replace(STYLE, styleHTML) : headPart + styleHTML;
// Cache an den Anfang, damit <use href> auch in geklonten Karten sofort auflösbar ist.
const out = head + cacheHTML + '\n' + bodyHTML + '\n' + tail;
fs.mkdirSync(path.dirname(outPath), {recursive: true});
fs.writeFileSync(outPath, out);
console.log(`Formeln: ${items.length}; TeX-Fehler: ${fehler}; Größe: ${(out.length / 1024).toFixed(1)} KB`);
