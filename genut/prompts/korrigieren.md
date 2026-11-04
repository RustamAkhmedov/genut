Ein automatischer Prüfer (SymPy, TeX-Prüfung, Graph-Auswertung) hat in einer Lernseite für Schüler (Fach: {{fach}}) Fehler gefunden. Korrigiere die betroffenen Elemente.

## Fehlerhafte Elemente

{{fehler}}

## Regeln

- Gib **jedes** oben genannte Element vollständig korrigiert zurück – in der passenden Liste (`bloecke`, `aufgaben`, `karten`, `fragen`) mit derselben `id`. Der Blocktyp (`typ`) bleibt gleich.
- Bei „Ergebnis falsch“: Rechne die Aufgabe selbst sorgfältig neu. Korrigiere **Lösungsweg und Ergebnis**. Passe den `check` nur an, wenn er die Angabe falsch abbildet – nie, um ein falsches Ergebnis passend zu machen.
- Bei TeX-Fehlern: gültiges TeX schreiben, Mathe nur in `\( … \)` bzw. `\[ … \]`, niemals `$`.
- Bei Quizfragen: `mc` braucht genau 4 `optionen` und `richtig` (0–3), `wahrfalsch` braucht `wahr` und keine `optionen`.
- Bei SQL-Fehlern: Beispieldaten (`schema_sql`) und Abfrage so korrigieren, dass sie in SQLite fehlerfrei laufen und das erwartete Ergebnis liefern.
- Bei Graph-Fehlern: Funktionsausdruck (SymPy-Syntax), x-Bereich oder Parameterbereich so wählen, dass die Funktion überall definiert ist.
- `quelle` bleibt unverändert. Ändere nichts, was nicht zur Korrektur nötig ist.


## Fach-Regeln (Auszug)

{{profil_regeln}}
