**SQL (Datenbanken)**
- SQL-Beispiele als `sql`-Block: `schema_sql` erzeugt kleine Beispieltabellen (CREATE TABLE + INSERT, 3–8 Zeilen je Tabelle, **SQLite-Dialekt**), `abfrage` ist die gezeigte Abfrage. Das Programm führt sie aus und zeigt das Ergebnis; auf der Lernseite kann der Schüler die Abfrage ändern und selbst ausführen.
- Verwende für zusammengehörige Beispiele dieselben Beispieltabellen (z. B. `schueler`, `klasse`, `fach`, `note`).
- DDL/Theorie ohne Ausführung (z. B. Oracle-spezifische Syntax) als `code`-Block mit `sprache: "sql"`.
- ER-Diagramme und Relationenmodelle als `diagramm`-Block (Mermaid `erDiagram`).
- SQL-Aufgaben bekommen einen `check` mit `art: "sql"`: `schema_sql` (Beispieldaten), `abfrage` (Musterlösung), `erwartet` (die Ergebniszeilen als Text, z. B. `[["Huber", "3"], ["Maier", "1"]]`), `reihenfolge: true` nur bei `ORDER BY`. Die Musterlösung steht auch im letzten Schritt als `sql`-Block.
- Normalformen, Schlüssel, Transaktionen: `definition`, `regel`, `tabelle` (Vorher/Nachher).
