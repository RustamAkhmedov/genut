// Formeln sicher machen (Constitution VI): TeX kann aus fremden Dateien kommen (Projekt-Austausch).
// `\href`, `\style`, `\bbox`, `\cssId`, `\class`, `\mmlToken` oder `\color` dürfen weder Links noch fremdes CSS
// noch eigene IDs erzeugen. Der Filter wirkt auf den Formelbaum, also unabhängig vom TeX-Paket.
// Genutzt von node/*.js (require) und von der Oberfläche (<script>, window.genutTexSicher).
(function (wurzel) {
  'use strict';
  const WEG = ['href', 'src', 'altimg', 'actiontype'];
  const NUR_MJX = /^\s*(mjx-[\w.-]*\s*)+$/i;           // eigene Kennungen von MathJax
  const FARBE = /^\s*(#[0-9a-f]{3,8}|[a-z-]+|(rgb|hsl)a?\([\d.%,\s]+\))\s*$/i;
  const FARB_ATTRIBUTE = ['mathcolor', 'mathbackground', 'color', 'background'];
  const SCHRIFT_ATTRIBUTE = ['fontfamily', 'fontweight', 'fontstyle'];
  const SCHRIFT = /^[\w\s,'-]*$/;
  // Erlaubte CSS-Eigenschaften; Werte ohne Funktionsaufrufe außer rgb()/hsl(), also nichts, das nachlädt
  const EIGENSCHAFT = /^(color|background-color|border(-(top|right|bottom|left))?(-(width|style|color))?|padding(-(top|right|bottom|left))?|margin(-(top|right|bottom|left))?|outline(-(width|style|color))?|font-(family|size|style|weight|variant)|opacity|text-shadow|vertical-align|letter-spacing)$/i;

  function wertOk(wert) {
    return !/[\\@<>]/.test(wert) && !wert.replace(/(rgb|hsl)a?\([\d.%,\s]*\)/gi, '').includes('(');
  }

  function css(text) {
    return String(text).split(';').filter((teil) => {
      const i = teil.indexOf(':');
      return i > 0 && EIGENSCHAFT.test(teil.slice(0, i).trim()) && wertOk(teil.slice(i + 1));
    }).map((teil) => teil.trim()).join('; ');
  }

  function knoten(k) {
    const attribute = k.attributes && k.attributes.getAllAttributes();
    if (!attribute) return;
    for (const name of Object.keys(attribute)) {
      const wert = attribute[name];
      if (WEG.includes(name) || /^on/i.test(name)) delete attribute[name];
      else if ((name === 'class' || name === 'id') && !NUR_MJX.test(String(wert))) delete attribute[name];
      else if (FARB_ATTRIBUTE.includes(name) && !FARBE.test(String(wert))) delete attribute[name];
      else if (SCHRIFT_ATTRIBUTE.includes(name) && !SCHRIFT.test(String(wert))) delete attribute[name];
      else if (name === 'style') {
        const rest = css(wert);
        if (rest) attribute[name] = rest; else delete attribute[name];
      }
    }
  }

  /** postFilter für den TeX-Eingang: `tex.postFilters.add(genutTexSicher)`. */
  function texSicher({ data }) {
    data.root.walkTree(knoten);  // math.root gibt es hier noch nicht
  }

  if (typeof module !== 'undefined' && module.exports) module.exports = texSicher;
  else wurzel.genutTexSicher = texSicher;
})(typeof window !== 'undefined' ? window : this);
