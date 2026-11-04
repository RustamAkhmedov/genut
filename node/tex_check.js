// Prüft TeX-Formeln. stdin: [{id, tex, display}], stdout: [{id, tex, fehler}] (nur fehlerhafte).
const {mathjax} = require('mathjax-full/js/mathjax.js');
const {TeX} = require('mathjax-full/js/input/tex.js');
const {SVG} = require('mathjax-full/js/output/svg.js');
const {liteAdaptor} = require('mathjax-full/js/adaptors/liteAdaptor.js');
const {RegisterHTMLHandler} = require('mathjax-full/js/handlers/html.js');
const {AllPackages} = require('mathjax-full/js/input/tex/AllPackages.js');

let input = '';
process.stdin.on('data', (d) => { input += d; });
process.stdin.on('end', () => {
  const items = JSON.parse(input || '[]');
  const adaptor = liteAdaptor();
  RegisterHTMLHandler(adaptor);
  const tex = new TeX({
    packages: AllPackages.filter(p => !['bussproofs', 'physics'].includes(p)),
    formatError: (jax, err) => { throw err; },
  });
  const doc = mathjax.document('', {InputJax: tex, OutputJax: new SVG({fontCache: 'none'})});
  const out = [];
  for (const it of items) {
    try {
      doc.convert(it.tex, {display: !!it.display});
    } catch (e) {
      out.push({id: it.id, tex: it.tex, fehler: String(e.message || e)});
    }
  }
  process.stdout.write(JSON.stringify(out));
});
