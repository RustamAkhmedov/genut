# gen_Ut – aus Mitschriften werden Lernseiten

Du lädst Fotos von Heft-, Tafel- oder Buchseiten hoch, oder Dateien wie Word, PowerPoint und PDF. Eine KI schreibt alles ab, du kontrollierst den Text. Danach baut die KI daraus eine **interaktive Lernseite**: Erklärungen, Lösungswege, Probeaufgaben, Karteikarten, ein Quiz und einen Spickzettel. Rechnungen, SQL-Abfragen, Subnetze, Reaktionsgleichungen und Strukturformeln rechnet ein Programm nach, bevor sie auf der Seite landen.

Heraus kommt **eine einzige HTML-Datei**. Sie funktioniert offline am Handy und am Laptop, im hellen und im dunklen Modus, und lässt sich per WhatsApp, Mail oder USB-Stick weitergeben.

> Gebaut für Schüler einer österreichischen HTL (4. Jahrgang Informatik), funktioniert aber für jedes Fach mit Mitschriften.

---

## Inhalt

1. [Die drei Versionen](#die-drei-versionen)
2. [Installation](#installation)
3. [Starten](#starten)
4. [So benutzt du gen_Ut](#so-benutzt-du-gen_ut)
5. [Die fertige Lernseite](#die-fertige-lernseite)
6. [Fächer und was sie Besonderes können](#fächer-und-was-sie-besonderes-können)
7. [Zwischen den KIs umschalten](#zwischen-den-kis-umschalten)
8. [Was das Programm nachprüft](#was-das-programm-nachprüft)
9. [Datenschutz](#datenschutz)
10. [Häufige Probleme](#häufige-probleme)
11. [Für Entwickler](#für-entwickler)
12. [Lizenz](#lizenz)

---

## Die drei Versionen

gen_Ut ist überall dasselbe Programm. Die Versionen unterscheiden sich nur darin, welche KI standardmäßig arbeitet. Das steht in einer Konfigurationsdatei im Ordner [`versionen/`](versionen/).

| | **Claude** | **Gemini** | **Lokal** |
|---|---|---|---|
| KI | Claude über die Claude-Code-CLI | Google Gemini (Flash-Modelle) | Ollama mit `gemma3:4b` auf deinem Computer – **experimentell** |
| Kosten | braucht ein Claude-Abo (Pro oder höher), verbraucht dessen Nutzung | **gratis** mit API-Schlüssel von Google AI Studio | gratis |
| Qualität | am besten: am meisten Inhalt, strengste Formatprüfung | gut, etwas knapper | einfacher, für kurze Unterlagen |
| Tempo pro Lernseite | ca. 3–10 Minuten | ca. 2 Minuten | je nach Computer deutlich länger |
| Grenze | Nutzungslimit deines Abos | ca. 20 Anfragen pro Tag und Modell (siehe unten) | keine |
| Daten | gehen an Anthropic | gehen an Google | bleiben auf deinem Computer |
| Datei | `versionen/claude.toml` | `versionen/gemini.toml` | `versionen/lokal.toml` |

**Was bedeutet „20 Anfragen pro Tag“ bei Gemini?** Eine Lernseite aus Dateien (docx, pdf, pptx …) braucht meist **1 Anfrage**. Aus Fotos kommt **1 Anfrage pro Foto** fürs Abschreiben dazu. gen_Ut wechselt automatisch zum nächsten Gemini-Modell, wenn eines überlastet ist oder sein Tageslimit erreicht hat. Realistisch sind damit etwa **10–20 Lernseiten aus Dateien** oder **5–10 aus Foto-Sätzen** pro Tag möglich.

**Welche soll ich nehmen?** Wenn du Claude Pro hast, nimm **Claude** und schalte für Kleinigkeiten auf Gemini um. Sonst nimm **Gemini**. **Lokal** ist für dich, wenn nichts deinen Computer verlassen soll.

> ⚠️ **Die lokale Version ist experimentell.** Ein kleines Modell auf dem Laptop ist deutlich langsamer und macht mehr Fehler als Claude oder Gemini. Rechne damit, dass Lernseiten knapper ausfallen und öfter nachgebessert werden müssen. Sie wurde noch nicht so ausführlich getestet wie die anderen beiden.

---

## Installation

Am einfachsten geht es mit dem **Setup-Skript**. Es richtet alles ein und fragt vor jeder Installation nach. Admin-Rechte braucht es nicht, nur die lokale Version unter Linux fragt für Ollama nach dem Passwort.

### 1. gen_Ut herunterladen

Unter [**Releases**](https://github.com/RustamAkhmedov/genut/releases/latest) das Zip deiner Version herunterladen und entpacken:

| Zip | Version |
|---|---|
| `genut-claude.zip` | Claude |
| `genut-gemini.zip` | Gemini |
| `genut-lokal.zip` | Lokal (experimentell) |

Oder mit git (dann fragt dich das Setup nach der Version):

```bash
git clone https://github.com/RustamAkhmedov/genut.git
```

### 2. Setup starten

**Windows:** Im entpackten Ordner **`setup.bat` doppelklicken**. Falls Windows warnt („Der Computer wurde durch Windows geschützt“), wähle „Weitere Informationen → Trotzdem ausführen“.

**macOS / Linux:** Terminal im Ordner öffnen und eingeben:

```bash
./setup.sh
```

(Unter macOS: Rechtsklick auf den Ordner → „Neues Terminal beim Ordner“. Falls `Permission denied` erscheint: `bash setup.sh`.)

### 3. Was das Setup macht

1. **Python 3.11+:** Ist es nicht vorhanden, lädt das Setup es nach Rückfrage über [uv](https://docs.astral.sh/uv/) in deinen Benutzerordner. Dann legt es eine eigene Python-Umgebung `.venv` an und installiert die Pakete.
2. **Node.js 20+:** Fehlt es, lädt das Setup nach Rückfrage eine eigene Kopie in den Ordner `.werkzeuge/`. Dann installiert es MathJax, Mermaid und sql.js.
3. **`config.toml`** für deine Version anlegen.
4. **KI einrichten:**
   - **Claude:** Claude Code installieren (offizieller Installer), unter Windows bei Bedarf auch Git. Danach meldest du dich einmal mit deinem Claude-Konto an.
   - **Gemini:** Das Setup öffnet https://aistudio.google.com/apikey. Dort holst du dir gratis einen Schlüssel und fügst ihn ein. Er landet in der Datei `.env` und bleibt auf deinem Computer.
   - **Lokal:** Ollama installieren und das Modell `gemma3:4b` herunterladen (ca. 3 GB).
5. **Startbefehl anlegen:** `start.bat` (Windows, auf Wunsch mit Desktop-Verknüpfung) bzw. `start.sh` (unter macOS zusätzlich `start.command` zum Doppelklicken).

Das Setup kannst du jederzeit nochmal starten. Es erkennt, was schon da ist, und kann auch die Version wechseln (`./setup.sh --version claude`, unter Windows `setup.bat -Version claude`). Mit `--ja` (Windows: `-Ja`) beantwortet es alle Rückfragen mit „ja“.

<details>
<summary><b>Ohne Setup-Skript (von Hand)</b></summary>

Voraussetzungen: Python 3.11+ und Node.js 20+.

```bash
python3 -m venv .venv
.venv/bin/pip install -e .          # Windows: .venv\Scripts\pip install -e .
npm ci
cp versionen/gemini.toml config.toml   # oder claude.toml / lokal.toml (Windows: copy)
```

Dann die KI einrichten:

- **Claude:** [Claude Code](https://claude.com/claude-code) installieren, einmal `claude` starten und anmelden.
- **Gemini:** Datei `.env` mit der Zeile `GEMINI_API_KEY=dein-schlüssel` anlegen (Schlüssel gratis auf https://aistudio.google.com/apikey).
- **Lokal:** [Ollama](https://ollama.com/download) installieren und `ollama pull gemma3:4b` ausführen.

</details>

---

## Starten

- **Windows:** `start.bat` doppelklicken (oder die Desktop-Verknüpfung „gen_Ut“).
- **macOS:** `start.command` doppelklicken oder im Terminal `./start.sh`.
- **Linux:** `./start.sh`

Der Browser öffnet sich automatisch mit **http://127.0.0.1:8765**. Das schwarze Fenster bzw. das Terminal muss offen bleiben, solange du gen_Ut benutzt. Beenden kannst du mit **Strg+C** oder indem du das Fenster schließt.

gen_Ut ist nur auf deinem eigenen Computer erreichbar, nicht im Netzwerk.

---

## So benutzt du gen_Ut

Ein Projekt durchläuft fünf Schritte. Oben im Projekt siehst du, wo du gerade bist.

### 1. Projekt anlegen

Auf **Neues Projekt** klicken:

- **Name:** z. B. „Integralrechnung“ oder „SQL Joins“. Er wird zum Titel der Lernseite.
- **Fach:** bestimmt, welche Bausteine die KI verwenden darf und was nachgeprüft wird (siehe [Fächer](#fächer-und-was-sie-besonderes-können)).
- **Modell:** welche KI dieses Projekt bearbeitet.
- **Probeaufgaben je Thema** (0–5), **Karteikarten** (automatisch oder fixe Anzahl), **Quizfragen je Thema** (0–10), **Erklärstil** (knapp oder ausführlich).

Diese Einstellungen kannst du später im Projekt unter **Einstellungen** ändern.

### 2. Fotos und Dateien hochladen

Du kannst die Dateien ins Fenster ziehen oder auswählen. Fotos und Dateien lassen sich mischen.

| Art | Formate | Was passiert |
|---|---|---|
| Fotos | jpg, png, webp, heic (iPhone) | Die KI schreibt sie ab. Skizzen und Graphen werden ausgeschnitten und erkannt. |
| Dokumente | docx, pptx, pdf, md, txt, html | Der Text wird direkt gelesen, ohne KI. Eingebettete Bilder werden wie Fotos behandelt. |
| Gescannte PDFs | pdf ohne Text | Jede Seite wird wie ein Foto abgeschrieben. |
| Google Docs | im Browser „Speichern unter → Webseite, komplett“ (html) | Wird eingelesen, große Exporte als Seitenbilder. |

Tipps für Fotos: gerade von oben, gutes Licht, eine Seite pro Foto. Danach auf **Transkribieren** klicken.

### 3. Transkripte kontrollieren

Für jede Datei siehst du nebeneinander **Original | Text-Editor | Vorschau**:

- Lies den Text durch und korrigiere Lesefehler. `[?]` markiert Stellen, bei denen die KI unsicher war.
- Formeln stehen als TeX, z. B. `\( x^2 \)`. Die Vorschau zeigt sie gerendert.
- Bei Dateien mit Überschriften gibt es eine **Themenauswahl**. Hake ab, was **nicht** auf die Lernseite soll, z. B. Kapitel, die nicht zur Schularbeit kommen.
- Im Foto kannst du zoomen und verschieben. Erkannte Skizzen sind eingerahmt.
- Wenn alles passt, klickst du auf **Kontrolliert ✓**.

Je genauer das Transkript, desto besser die Lernseite. Die KI erfindet nichts dazu, was im Transkript falsch steht.

### 4. Generieren

Auf **Generieren** klicken. Die KI erstellt Themen, Erklärungen, Lösungswege, Probeaufgaben, Karteikarten und Quizfragen. Danach prüft das Programm alles nach (siehe [unten](#was-das-programm-nachprüft)). Fehler schickt es zur Korrektur an die KI zurück. Den Fortschritt siehst du live.

### 5. Vorschau und Feinschliff

Die fertige Lernseite erscheint direkt in der Vorschau. Links ist eine Liste aller Elemente:

- **Löschen:** Elemente, die du nicht brauchst.
- **Neu generieren mit Hinweis:** z. B. „ausführlicher“, „mit Zahlenbeispiel“ oder „auf Englisch“.
- **Ergänzen …:** fehlende Themen aus denselben Unterlagen nachgenerieren lassen.
- **JSON bearbeiten:** für Profis. Der Editor prüft deine Änderung, bevor er speichert.
- **Weitere Seiten nachreichen:** im Schritt **Fotos** hochladen, transkribieren, kontrollieren und wieder **Generieren**. Bestehende Inhalte bleiben dabei unverändert, nur das Neue kommt dazu.

Diagramme (UML, ER, Gantt …) werden beim ersten Öffnen der Vorschau gezeichnet und in die Seite eingebaut.

### 6. Herunterladen

Unter **Export → Herunterladen** bekommst du die fertige HTML-Datei. Mehr braucht es nicht: Datei aufs Handy schicken, öffnen, lernen.

---

## Die fertige Lernseite

| Bereich | Inhalt |
|---|---|
| **Start** | Überblick über alle Themen mit Lernfortschritt |
| **Lernen** | Ein Thema nach dem anderen mit Definitionen, Regeln, Formeln, Beispielen, Code, Diagrammen, interaktiven Graphen mit Schiebereglern und typischen Fehlern |
| **Aufgaben** | Aufgaben aus deinen Unterlagen und Probeaufgaben: Lösungsweg Schritt für Schritt aufdecken, Ergebnis vom Programm geprüft |
| **Karten** | Karteikarten zum Umdrehen, „gewusst / nochmal“ |
| **Quiz** | Multiple Choice und Wahr/Falsch mit Erklärung. Falsch beantwortete Fragen kommen am Ende nochmal. |
| **Spickzettel** | Das Wichtigste auf einer Seite, gut zum Ausdrucken |

Dein Fortschritt (gelesen, gewusst, Quiz) wird im Browser gespeichert und überlebt ein Neuladen. Die Seite lädt nichts aus dem Internet nach.

Blöcke mit **KI**-Abzeichen hat die KI ergänzt, alles andere stammt aus deinen Unterlagen. **✓ geprüft** heißt: vom Programm nachgerechnet.

---

## Fächer und was sie Besonderes können

| Fach | Besonderheiten |
|---|---|
| **Mathematik** | Rechenwege; Ergebnisse von SymPy nachgerechnet; Funktionsgraphen mit Schiebereglern für Parameter |
| **Physik** | wie Mathe, zusätzlich Prüfung von **Zahl und Einheit** (z. B. km/h → m/s) |
| **Chemie** | Reaktionsgleichungen (Atome und Ladungen geprüft); **Strukturformeln** als Valenzstrich- und Skelettformel gezeichnet, mit Summen- und Halbstrukturformel |
| **POS, WMC, DSAI** (Programmieren) | Code mit Zeilen-Erklärungen, Befehle zum Kopieren, Code-Quiz. Code wird *nicht* ausgeführt. |
| **DBI** (Datenbanken) | SQL-Abfragen werden echt ausgeführt (SQLite), das Ergebnis steht als Tabelle daneben; ER-Diagramme |
| **NSCS** (Netzwerke) | Subnetz-Berechnungen geprüft (IPv4 und IPv6); interaktiver Subnetzrechner auf der Seite |
| **Englisch** | Inhalte auf Englisch, Erklärungen auf Deutsch; Vokabeln werden automatisch zu Karteikarten; Lückentexte; Textsorten (z. B. Cover Letter) |
| **Deutsch** | Lückentexte für Grammatik und Rechtschreibung, Textsorten, Literatur (Werk, Epoche, Motive) |
| **Geographie, SYP** | Zeitleisten, Klimadiagramme, Tabellen; Gantt, Projektstrukturplan, UML als Diagramme |
| **Sonstiges** | für alles andere |

Jedes Fach hat auf der Lernseite eine eigene Akzentfarbe.

---

## Zwischen den KIs umschalten

Oben rechts im Tool ist der **KI-Schalter**, z. B. **Claude | Gemini**:

- **Auf der Projektübersicht** legt er fest, welche KI neue Projekte bekommen.
- **In einem Projekt** stellt er zusätzlich die KI dieses Projekts um.

Welche KIs im Schalter auftauchen, steht in `config.toml` unter `[modell] auswahl`. Damit Gemini dort funktioniert, braucht es den Schlüssel in der `.env`, damit Claude funktioniert, die angemeldete Claude-CLI. Eine Verbindung testen kannst du unter **Einstellungen → Verbindung testen**.

---

## Was das Programm nachprüft

Die KI liefert nur Daten. Die Seite selbst baut ein normales Programm nach festen Vorlagen. Bevor etwas auf der Seite landet, wird es geprüft:

- **Mathe:** SymPy rechnet Ergebnisse, Gleichungslösungen und Integrale nach. Graphen müssen im ganzen Bereich definiert sein, und jeder Schieberegler muss die Kurve wirklich verändern.
- **Physik:** Zahl *und* Einheit müssen stimmen.
- **Chemie:** Reaktionsgleichungen müssen ausgeglichen sein (Atome und Ladung). Summen- und Halbstrukturformel müssen zum gezeichneten Molekül passen.
- **SQL:** Jede Abfrage wird in einer Test-Datenbank ausgeführt.
- **Subnetze:** Netz- und Broadcastadresse, Hosts und Maske werden nachgerechnet.
- **Überall:** Formeln müssen fehlerfrei rendern, und Quizfragen müssen beantwortbar sein.

Was falsch ist, geht automatisch zur Korrektur zurück an die KI. Bleibt etwas falsch, steht auf der Seite deutlich **„⚠ Konnte nicht bestätigt werden – bitte selbst nachrechnen“**. Der Prüfer läuft in einem abgeschotteten Prozess mit Zeitlimit.

Trotzdem gilt: Die KI kann sich bei Erklärungen irren. Lies die Seite durch, bevor du für eine Schularbeit darauf vertraust.

---

## Datenschutz

- gen_Ut läuft **auf deinem Computer**. Projekte liegen im Ordner `projekte/`.
- Bei **Claude** und **Gemini** werden deine Fotos und Texte zur Verarbeitung an Anthropic bzw. Google geschickt. Lade nichts hoch, was du dort nicht haben willst (z. B. Fotos mit Namen von Mitschülern).
- Bei **Lokal** verlässt nichts deinen Computer.
- Die fertige Lernseite enthält keine Tracker und lädt nichts nach.

---

## Häufige Probleme

| Problem | Lösung |
|---|---|
| `claude: command not found` | Claude Code installieren und einmal `claude` im Terminal starten und anmelden. |
| „Kein Gemini-Schlüssel“ | `.env` im gen_Ut-Ordner anlegen mit `GEMINI_API_KEY=…` und den Server neu starten. |
| „Gemini ist gerade überlastet“ | Ein paar Minuten warten oder oben auf Claude umschalten. gen_Ut probiert schon von selbst andere Gemini-Modelle. |
| „Tageslimit … erreicht“ | Das Gratis-Kontingent für heute ist aufgebraucht. Morgen geht es wieder, oder du nutzt bis dahin eine andere KI. |
| „Ollama nicht erreichbar“ | Ollama starten (`ollama serve`) und prüfen, ob das Modell da ist (`ollama list`). |
| `npm: command not found` | Setup nochmal starten. Es lädt Node.js bei Bedarf selbst herunter. |
| Setup bricht ab | Die letzten Zeilen der Fehlermeldung lesen. Ausführliche Protokolle stehen in `.werkzeuge/pip.log` und `.werkzeuge/npm.log`. |
| Port 8765 belegt | In `config.toml` unter `[server]` einen anderen `port` eintragen. |
| Diagramm zeigt nur Text | Projekt einmal im Tool unter **Vorschau** öffnen, dann wird es gezeichnet und gespeichert. |
| Transkript schlecht | Besseres Foto (Licht, gerade, scharf) oder Text im Editor korrigieren und **Neu transkribieren**. |

---

## Für Entwickler

```bash
.venv/bin/pip install -e '.[dev]'          # zusätzlich pytest, playwright, jsonschema
.venv/bin/python -m pytest -q              # alle Tests (Browser-Tests brauchen Chrome/Chromium)
```

Befehle:

```bash
python -m genut serve                                   # Web-Oberfläche
python -m genut neu "Titel" foto1.jpg foto2.heic        # Projekt im Terminal anlegen
python -m genut run <slug>                              # ganze Pipeline ohne Kontrolle (zum Testen)
python -m genut render tests/fixtures/integral x.html   # Beispiel-Dokument ohne KI rendern
```

Aufbau:

| Ordner | Inhalt |
|---|---|
| `genut/pipeline.py` | Ablauf: Einlesen → Transkribieren → Anreichern → Prüfen → Korrigieren → Bauen |
| `genut/schema.py` | Datenmodell der Lernseite (Pydantic) und das JSON-Schema für die KI |
| `genut/faecher.py` | Fächer, Profile, erlaubte Bausteine und Prüfarten |
| `genut/pruefer/` | Nachprüfung (SymPy, Einheiten, Chemie, SQL, Subnetze) im abgeschotteten Arbeiterprozess |
| `genut/modelle/` | Anbindung der KIs: `claude_code.py`, `gemini.py`, `ollama.py` |
| `genut/render/` | Vorlagen, CSS/JS der Lernseite, Strukturformeln (RDKit) |
| `genut/prompts/` | Anweisungen an die KI |
| `node/` | MathJax-Vorberechnung (Formeln werden offline in SVG umgewandelt) |
| `ui/` | Web-Oberfläche des Tools |
| `versionen/` | Konfiguration der drei Versionen |
| `setup.sh`, `setup.ps1`, `setup.bat` | Einrichtung für macOS/Linux und Windows |

---

## Lizenz

[MIT](LICENSE): Du darfst gen_Ut frei benutzen, verändern und weitergeben, auch in veränderter Form, solange der Lizenzhinweis dabei bleibt. Es gibt keine Gewährleistung.
