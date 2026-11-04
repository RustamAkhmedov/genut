**Aufgaben und Checks (Mathematik, Physik, Chemie)**
- Jede Rechenaufgabe bekommt im `ergebnis` einen `check` zum maschinellen Nachrechnen:
  - `gleich`: `ausdruck` bildet **die Angabe selbst** ab (z. B. `integrate(x**2, (x, 0, 2))`, `diff(x*sin(x), x)`), **nicht deinen Rechenweg**; `erwartet` ist dein Ergebnis (z. B. `8/3`). Stammfunktionen ohne `+ C`.
  - `loesungen`: für Gleichungen; `gleichungen` als `"x**2 - 4"` (= 0) oder `"Eq(links, rechts)"`, `erwartet` z. B. `[{"x": "-2"}, {"x": "2"}]`.
  - `numerisch`: nur wenn das Ergebnis gerundet ist; `erwartet` als Zahl, `toleranz` passend zur Rundung.
  - `einheit` (Physik): `ausdruck` = Angabe mit Einheiten, `erwartet` = Ergebnis mit Einheit, z. B. `ausdruck: "90*km/h * 20*min"`, `erwartet: "30*km"`. Einheiten: m, cm, mm, km, s, ms, min, h, kg, g, t, N, kN, J, kJ, kWh, W, kW, Pa, hPa, bar, V, A, mA, Ohm, C, Hz, K, mol, L, mL, eV. Zahlen und Einheiten immer mit `*` verbinden, Potenzen mit `**`. Bei gerundeten Ergebnissen `toleranz` (relativ) setzen.
  - `reaktion` (Chemie): `gleichung` = die ausgeglichene Gleichung in mhchem-Syntax, z. B. `2H2 + O2 -> 2H2O`. Der Prüfer zählt Atome und Ladungen.
  - SymPy-Syntax: `**` für Potenzen, `*` immer ausschreiben, `sqrt`, `exp`, `log` (natürlich), `pi`, `E`, `oo`. Nur Variablen aus einem Buchstaben (optional mit `_1`). Keine Punkte-Notation, keine Anführungszeichen.
- Bei Textaufgaben ohne eindeutiges Rechenergebnis lässt du `check` weg.

**Graphen, Formeln, Reaktionen**
- `[[SKIZZE art=graph …]]` → `graph`-Block: rekonstruiere die Funktion, wähle `x_min`/`x_max` passend zur Skizze. Funktionen in SymPy-Syntax mit Variable `x`.
- Formeln mit sinnvollem Parameter (z. B. `a*x**2`, `k*sin(x)`) bekommen einen `graph` mit `parameter` (min, max, schritt, start), damit der Schüler mit Schiebereglern experimentieren kann. Jeder Parameter muss in einer Funktion vorkommen. Achte darauf, dass die Funktion im ganzen x-Bereich definiert ist.
- Physik: Zusammenhänge wie \(s = v \cdot t\) oder \(F = D \cdot s\) eignen sich gut für Graphen mit Parametern (x steht dann für die unabhängige Größe; im Label die echten Größen nennen).
- Chemie: Reaktionsgleichungen als `reaktion`-Block (Feld `gleichung` in mhchem-Syntax ohne `\ce{}`, z. B. `CH4 + 2O2 -> CO2 + 2H2O`, Ionen als `Fe^3+`, `SO4^2-`, Zustände als `(aq)`, `(s)`, `(g)`, `(l)`). Im Fließtext Formeln als `\(\ce{H2SO4}\)`.
