"""Erzeugt die Profil-Fixtures tests/fixtures/<profil>/inhalt.json (einmalig bzw. nach Änderungen ausführen).

    .venv/bin/python tests/fixtures/profile_erzeugen.py
"""
import json
from pathlib import Path

HIER = Path(__file__).parent


def frage_mc(i, thema, frage, optionen, richtig, erkl, **extra):
    return {"id": f"q-{i:08d}", "thema_id": thema, "quelle": "ki", "art": "mc", "frage_md": frage,
            "optionen": optionen, "richtig": richtig, "erklaerung_md": erkl, **extra}


def frage_wf(i, thema, aussage, wahr, erkl):
    return {"id": f"q-{i:08d}", "thema_id": thema, "quelle": "ki", "art": "wahrfalsch", "frage_md": aussage,
            "wahr": wahr, "erklaerung_md": erkl}


def karte(i, thema, vorne, hinten):
    return {"id": f"k-{i:08d}", "thema_id": thema, "quelle": "ki", "vorne_md": vorne, "hinten_md": hinten}


def aufgabe(i, thema, titel, angabe, schritte, ergebnis, check=None, art="foto"):
    return {"id": f"a-{i:08d}", "art": art, "quelle": "foto" if art == "foto" else "ki", "thema_id": thema,
            "titel": titel, "schwierigkeit": 2, "angabe_md": angabe, "rechenaufgabe": check is not None,
            "schritte": [{"titel": t, "quelle": "ki", "bloecke": b} for t, b in schritte],
            "ergebnis": {"md": ergebnis, "check": check}}


def txt(i, md, **k):
    return {"id": f"b-{i:08d}", "typ": "text", "quelle": "ki", "md": md, **k}


FIXTURES = {}

# ---------------------------------------------------------------- Naturwissenschaften (Chemie + Physik)
T1, T2 = "t-00000101", "t-00000102"
FIXTURES["naturwiss"] = {
    "projekt": {"titel": "Stöchiometrie & Kinematik", "untertitel": "Chemie und Physik", "fach": "chemie"},
    "themen": [
        {"id": T1, "titel": "Reaktionsgleichungen und Rauchgasentschwefelungsanlagenbetrieb", "kurz": "Atome und Ladungen ausgleichen", "quelle": "foto", "bloecke": [
            {"id": "b-00000101", "typ": "definition", "quelle": "foto", "begriff": "Stoffmenge",
             "md": "Die Stoffmenge \\(n\\) gibt die Teilchenzahl in Mol an: \\(n = \\frac{m}{M}\\).", "spick": True},
            {"id": "b-00000102", "typ": "reaktion", "quelle": "foto", "titel": "Knallgasreaktion",
             "gleichung": "2H2 + O2 -> 2H2O", "erklaerung_md": "Wasserstoff verbrennt mit Sauerstoff zu Wasser.", "spick": True},
            {"id": "b-00000103", "typ": "reaktion", "quelle": "ki", "titel": "Fällung",
             "gleichung": "Fe^3+ + 3OH- -> Fe(OH)3 v", "erklaerung_md": "Eisen(III)-hydroxid fällt aus."},
            {"id": "b-00000104", "typ": "reaktion", "quelle": "ki", "titel": "Absichtlich falsch (Testfall)",
             "gleichung": "H2 + O2 -> H2O"},
            txt(105, "Im Fließtext: \\(\\ce{H2SO4}\\) ist Schwefelsäure, \\(\\ce{SO4^2-}\\) das Sulfat-Ion."),
            {"id": "b-00000106", "typ": "struktur", "quelle": "foto", "name": "Essigsäureethylester", "smiles": "CC(=O)OCC",
             "summenformel": "C4H8O2", "halbstruktur": "CH3-COO-CH2-CH3", "darstellung": "beide",
             "erklaerung_md": "Ester aus Essigsäure und Ethanol.", "spick": True},
            {"id": "b-00000107", "typ": "struktur", "quelle": "ki", "name": "cis-But-2-en", "smiles": "C/C=C\\C",
             "summenformel": "C4H8", "halbstruktur": "CH3-CH=CH-CH3", "darstellung": "valenzstrich"},
            {"id": "b-00000108", "typ": "struktur", "quelle": "ki", "name": "Benzol", "smiles": "c1ccccc1",
             "summenformel": "C6H6", "darstellung": "skelett"},
            {"id": "b-00000109", "typ": "struktur", "quelle": "ki", "name": "Absichtlich falsch (Testfall)", "smiles": "CCO",
             "summenformel": "C2H4O", "halbstruktur": "CH3-CH2-OH"},
        ]},
        {"id": T2, "titel": "Gleichförmige Bewegung", "kurz": "Weg, Zeit, Geschwindigkeit", "quelle": "foto", "bloecke": [
            {"id": "b-00000111", "typ": "formel", "quelle": "foto", "titel": "Weg-Zeit-Gesetz", "tex": "s = v \\cdot t",
             "variablen": [{"name": "s", "bedeutung": "Weg in m"}, {"name": "v", "bedeutung": "Geschwindigkeit in m/s"}],
             "graph": {"x_min": 0, "x_max": 10, "funktionen": [{"ausdruck": "v*x", "label": "s(t)"}],
                       "parameter": [{"name": "v", "min": 0.5, "max": 5, "schritt": 0.5, "start": 2, "bedeutung": "Geschwindigkeit in m/s"}]},
             "spick": True},
        ]},
    ],
    "aufgaben": [
        aufgabe(101, T1, "Verbrennung von Methan", "Gleiche die Reaktion \\(\\ce{CH4 + O2 -> CO2 + H2O}\\) aus.",
                [("Kohlenstoff und Wasserstoff", [txt(121, "C: 1 = 1, H: 4 → 2 Wasser.")])],
                "\\(\\ce{CH4 + 2O2 -> CO2 + 2H2O}\\)", {"art": "reaktion", "gleichung": "CH4 + 2O2 -> CO2 + 2H2O"}),
        aufgabe(102, T2, "Zugfahrt", "Ein Zug fährt 20 Minuten mit 90 km/h. Wie weit kommt er?",
                [("Formel", [txt(122, "\\(s = v \\cdot t\\)")])],
                "\\(s = 30\\,\\mathrm{km}\\)", {"art": "einheit", "ausdruck": "90*km/h * 20*min", "erwartet": "30*km"}),
        aufgabe(103, T2, "Falsche Einheit (Testfall)", "Wie weit kommt man in 3 s mit 12 m/s?",
                [("Rechnen", [txt(123, "\\(s = 12 \\cdot 3\\)")])],
                "\\(s = 36\\,\\mathrm{s}\\)", {"art": "einheit", "ausdruck": "12*m/s * 3*s", "erwartet": "36*s"}, art="probe"),
    ],
    "karten": [karte(101, T1, "Was bleibt bei einer Reaktion erhalten?", "Atome jedes Elements und die Ladung.")],
    "quiz": [
        frage_mc(101, T1, "Welche Gleichung ist ausgeglichen?",
                 ["\\(\\ce{H2 + O2 -> H2O}\\)", "\\(\\ce{2H2 + O2 -> 2H2O}\\)", "\\(\\ce{H2 + 2O2 -> H2O}\\)", "\\(\\ce{2H2 + 2O2 -> H2O}\\)"],
                 1, "Links 4 H und 2 O, rechts ebenfalls.", check={"art": "reaktion", "gleichung": "2H2 + O2 -> 2H2O"}),
        frage_wf(102, T2, "Bei doppelter Geschwindigkeit halbiert sich der Weg in derselben Zeit.", False,
                 "Der Weg verdoppelt sich: \\(s = v \\cdot t\\)."),
        frage_mc(103, T2, "Wie viele m/s sind 72 km/h?", ["\\(20\\)", "\\(7{,}2\\)", "\\(36\\)", "\\(259{,}2\\)"], 0,
                 "\\(72 : 3{,}6 = 20\\)", check={"art": "einheit", "ausdruck": "72*km/h", "erwartet": "20*m/s"}),
    ],
}

# ---------------------------------------------------------------- Programmieren (POS)
T1, T2 = "t-00000201", "t-00000202"
JAVA = """public class Zaehler {
    private int wert = 0;

    public void erhoehen() {
        wert++;
    }

    public int getWert() {
        return wert;
    }
}"""
FIXTURES["programmieren"] = {
    "projekt": {"titel": "Klassen und Objekte", "untertitel": "POS · 4. Jahrgang", "fach": "pos"},
    "themen": [
        {"id": T1, "titel": "Klassen in Java", "kurz": "Attribute, Methoden, Kapselung", "quelle": "foto", "bloecke": [
            {"id": "b-00000201", "typ": "definition", "quelle": "foto", "begriff": "Kapselung",
             "md": "Attribute sind `private`, Zugriff nur über Methoden (Getter/Setter).", "spick": True},
            {"id": "b-00000202", "typ": "code", "quelle": "foto", "sprache": "java", "code": JAVA,
             "erklaerungen": [{"zeilen": "1", "md": "Öffentliche Klasse `Zaehler`."},
                              {"zeilen": "2", "md": "Privates Attribut, startet bei 0."},
                              {"zeilen": "4-6", "md": "Methode erhöht den Wert um 1."},
                              {"zeilen": "8-10", "md": "Getter gibt den aktuellen Wert zurück."}]},
            {"id": "b-00000203", "typ": "hinweis", "quelle": "ki", "art": "falle",
             "md": "Strings mit `equals` vergleichen, nicht mit `==`."},
            {"id": "b-00000204", "typ": "diagramm", "quelle": "ki", "titel": "Klassendiagramm",
             "mermaid": "classDiagram\n  class Zaehler {\n    -int wert\n    +erhoehen() void\n    +getWert() int\n  }"},
        ]},
        {"id": T2, "titel": "Schleifen", "kurz": "for und while", "quelle": "ki", "bloecke": [
            {"id": "b-00000211", "typ": "code", "quelle": "ki", "sprache": "java",
             "code": "for (int i = 0; i < 3; i++) {\n    System.out.println(i * 2);\n}"},
            {"id": "b-00000212", "typ": "befehl", "quelle": "ki", "befehl": "javac Main.java && java Main",
             "erklaerung_md": "Kompilieren und ausführen.", "kontext": "bash"},
        ]},
    ],
    "aufgaben": [
        aufgabe(201, T1, "Getter schreiben", "Schreibe einen Getter für das Attribut `name`.",
                [("Lösung", [{"id": "b-00000221", "typ": "code", "quelle": "ki", "sprache": "java",
                              "code": "public String getName() {\n    return name;\n}"}])],
                "Methode `getName()` gibt `name` zurück."),
    ],
    "karten": [karte(201, T1, "Was bedeutet `private`?", "Nur innerhalb der Klasse sichtbar.")],
    "quiz": [
        frage_mc(201, T2, "Was gibt dieses Programm aus?\n\n```java\nfor (int i = 0; i < 3; i++) {\n    System.out.print(i * 2 + \" \");\n}\n```",
                 ["`0 2 4`", "`2 4 6`", "`0 1 2`", "`0 2 4 6`"], 0, "i läuft von 0 bis 2, ausgegeben wird i·2."),
        frage_wf(202, T1, "Ein `private`-Attribut kann von jeder anderen Klasse direkt gelesen werden.", False,
                 "`private` ist nur innerhalb der eigenen Klasse sichtbar."),
        frage_mc(203, T1, "Wo ist der Fehler?\n\n```java\nString a = \"Hallo\";\nif (a == \"Hallo\") { }\n```",
                 ["Strings mit `==` vergleichen", "Fehlendes Semikolon", "`String` klein geschrieben", "Kein Fehler"], 0,
                 "`==` vergleicht Referenzen; richtig ist `a.equals(\"Hallo\")`. Template: `${x}` ist kein Java."),
    ],
}

# ---------------------------------------------------------------- Datenbanken (DBI)
T1 = "t-00000301"
SCHEMA = ("CREATE TABLE schueler(id INTEGER PRIMARY KEY, name TEXT, klasse TEXT, note INTEGER);\n"
          "INSERT INTO schueler VALUES (1,'Huber','4A',2),(2,'Maier','4A',1),(3,'Gruber','4B',3),(4,'Wagner','4B',2);")
FIXTURES["datenbanken"] = {
    "projekt": {"titel": "SQL-Abfragen", "untertitel": "DBI · Gruppieren", "fach": "dbi"},
    "themen": [
        {"id": T1, "titel": "GROUP BY und Aggregatfunktionen", "kurz": "Zusammenfassen von Zeilen", "quelle": "foto", "bloecke": [
            {"id": "b-00000301", "typ": "regel", "quelle": "foto", "titel": "Aggregatfunktionen",
             "md": "`COUNT`, `SUM`, `AVG`, `MIN`, `MAX` fassen mehrere Zeilen zusammen.", "beispiele": ["`SELECT COUNT(*) FROM schueler`"], "spick": True},
            {"id": "b-00000302", "typ": "sql", "quelle": "foto", "titel": "Schüler je Klasse", "schema_sql": SCHEMA,
             "abfrage": "SELECT klasse, COUNT(*) AS anzahl\nFROM schueler\nGROUP BY klasse\nORDER BY klasse;",
             "erklaerung_md": "`GROUP BY` bildet eine Gruppe je Klasse."},
            {"id": "b-00000303", "typ": "sql", "quelle": "ki", "aufgabe_md": "Gib den Notendurchschnitt der Klasse 4B aus.",
             "schema_sql": SCHEMA, "abfrage": "SELECT AVG(note) AS schnitt FROM schueler WHERE klasse = '4B';"},
            {"id": "b-00000304", "typ": "sql", "quelle": "ki", "titel": "Absichtlich falsch (Testfall)",
             "schema_sql": SCHEMA, "abfrage": "SELECT * FROM gibtsnicht;"},
            {"id": "b-00000305", "typ": "diagramm", "quelle": "ki", "titel": "ER-Diagramm",
             "mermaid": "erDiagram\n  KLASSE ||--o{ SCHUELER : hat\n  SCHUELER {\n    int id\n    string name\n  }"},
        ]},
    ],
    "aufgaben": [
        aufgabe(301, T1, "Beste Note je Klasse", "Gib für jede Klasse die beste Note aus.",
                [("Abfrage", [{"id": "b-00000321", "typ": "sql", "quelle": "ki", "schema_sql": SCHEMA,
                               "abfrage": "SELECT klasse, MIN(note) FROM schueler GROUP BY klasse;"}])],
                "4A: 1, 4B: 2",
                {"art": "sql", "schema_sql": SCHEMA, "abfrage": "SELECT klasse, MIN(note) FROM schueler GROUP BY klasse;",
                 "erwartet": [["4A", "1"], ["4B", "2"]], "reihenfolge": False}),
    ],
    "karten": [karte(301, T1, "Wofür steht `HAVING`?", "Filtert Gruppen nach dem Gruppieren.")],
    "quiz": [
        frage_mc(301, T1, "Welche Klausel filtert **Gruppen**?", ["`WHERE`", "`HAVING`", "`ORDER BY`", "`LIMIT`"], 1,
                 "`WHERE` filtert Zeilen vor, `HAVING` Gruppen nach dem Gruppieren."),
        frage_wf(302, T1, "`COUNT(*)` zählt auch Zeilen mit NULL-Werten.", True, "`COUNT(*)` zählt alle Zeilen."),
    ],
}

# ---------------------------------------------------------------- Netzwerk (NSCS)
T1 = "t-00000401"
FIXTURES["netzwerk"] = {
    "projekt": {"titel": "Subnetting", "untertitel": "NSCS · IPv4 und IPv6", "fach": "nscs"},
    "themen": [
        {"id": T1, "titel": "IPv4-Subnetting", "kurz": "Netz, Broadcast, Hosts", "quelle": "foto", "bloecke": [
            {"id": "b-00000401", "typ": "regel", "quelle": "foto", "titel": "Nutzbare Hosts",
             "md": "Bei Präfix \\(p\\) gibt es \\(2^{32-p} - 2\\) nutzbare Hosts.", "spick": True},
            {"id": "b-00000402", "typ": "subnetzrechner", "quelle": "ki", "start": "192.168.10.77/26"},
            {"id": "b-00000403", "typ": "befehl", "quelle": "foto", "befehl": "ip address add 192.168.10.65/26 dev eth0",
             "erklaerung_md": "Adresse unter Linux setzen.", "kontext": "bash"},
            {"id": "b-00000404", "typ": "subnetzrechner", "quelle": "ki", "titel": "Absichtlich falsch (Testfall)", "start": "300.1.1.1/24"},
            {"id": "b-00000405", "typ": "diagramm", "quelle": "ki", "titel": "TCP-Handshake",
             "mermaid": "sequenceDiagram\n  Client->>Server: SYN\n  Server->>Client: SYN-ACK\n  Client->>Server: ACK"},
        ]},
    ],
    "aufgaben": [
        aufgabe(401, T1, "Subnetz bestimmen", "Bestimme Netzadresse, Broadcast und Hostanzahl für 192.168.10.77/26.",
                [("Maske", [txt(421, "/26 → 255.255.255.192, Blockgröße 64.")])],
                "Netz 192.168.10.64, Broadcast 192.168.10.127, 62 Hosts",
                {"art": "subnetz", "netz": "192.168.10.77/26",
                 "erwartet": {"netzadresse": "192.168.10.64", "broadcast": "192.168.10.127", "hosts": 62}}),
        aufgabe(402, T1, "IPv6-Präfix", "Wie lautet das Netz von 2001:db8:abcd:12::1/64?",
                [("Präfix", [txt(422, "Die ersten 64 Bit bleiben.")])], "2001:db8:abcd:12::/64",
                {"art": "subnetz", "netz": "2001:db8:abcd:12::1/64", "erwartet": {"netzadresse": "2001:db8:abcd:12::"}}, art="probe"),
    ],
    "karten": [karte(401, T1, "Maske zu /26?", "255.255.255.192")],
    "quiz": [
        frage_mc(401, T1, "Wie viele nutzbare Hosts hat ein /27-Netz?", ["30", "32", "62", "14"], 0, "\\(2^5 - 2 = 30\\)"),
        frage_wf(402, T1, "Die Broadcast-Adresse von 10.0.0.0/8 ist 10.255.255.255.", True, "Alle Hostbits auf 1."),
    ],
}

# ---------------------------------------------------------------- Sprachen (Englisch)
T1, T2 = "t-00000501", "t-00000502"
FIXTURES["sprachen"] = {
    "projekt": {"titel": "Past Simple & Formal Letters", "untertitel": "Englisch · 4. Jahrgang", "fach": "englisch", "sprache": "de"},
    "themen": [
        {"id": T1, "titel": "Past Simple", "kurz": "Abgeschlossene Handlungen in der Vergangenheit", "quelle": "foto", "bloecke": [
            {"id": "b-00000501", "typ": "regel", "quelle": "foto", "titel": "Bildung",
             "md": "Regelmäßige Verben: Grundform + *-ed*. Verneinung mit *didn't* + Grundform.",
             "beispiele": ["I *worked* yesterday.", "She *didn't go* to school."], "spick": True},
            {"id": "b-00000502", "typ": "lueckentext", "quelle": "ki", "titel": "Übung",
             "anweisung_md": "Setze das Verb im Past Simple ein.",
             "text": "Yesterday I [[played]] football. We [[didn't win|did not win]] the match. Then we [[went]] home."},
            {"id": "b-00000503", "typ": "vokabel", "quelle": "foto", "wort": "to achieve", "uebersetzung": "erreichen", "beispiel": "She achieved her goal."},
            {"id": "b-00000504", "typ": "vokabel", "quelle": "foto", "wort": "reliable", "uebersetzung": "zuverlässig"},
            {"id": "b-00000505", "typ": "lueckentext", "quelle": "ki", "titel": "Absichtlich falsch (Testfall)", "text": "Kein einziges Feld."},
        ]},
        {"id": T2, "titel": "Formal Letter", "kurz": "Aufbau eines formellen Briefs", "quelle": "foto", "bloecke": [
            {"id": "b-00000511", "typ": "textsorte", "quelle": "foto", "name": "Formal Letter",
             "zweck_md": "Bewerbung, Beschwerde oder Anfrage an eine Firma.",
             "aufbau": ["Sender's address", "Date", "Recipient's address", "Salutation: *Dear Sir or Madam,*", "Body", "Closing: *Yours faithfully,*"],
             "merkmale": ["Keine Kurzformen", "Höflicher, sachlicher Ton"],
             "formulierungen": ["I am writing to …", "I look forward to hearing from you."]},
            {"id": "b-00000512", "typ": "werk", "quelle": "ki", "titel": "Animal Farm", "autor": "George Orwell", "jahr": "1945",
             "gattung": "Fabel", "inhalt_md": "Tiere vertreiben den Bauern, doch die Schweine werden zu neuen Herrschern.",
             "motive": ["Macht", "Propaganda"], "zitat": "All animals are equal, but some animals are more equal than others."},
        ]},
    ],
    "aufgaben": [
        aufgabe(501, T2, "Write a complaint", "Write a formal letter complaining about a late delivery.",
                [("Musterlösung", [txt(521, "Dear Sir or Madam, I am writing to complain …")])], "Siehe Musterlösung."),
    ],
    "karten": [karte(501, T1, "Past Simple von *go*?", "*went*")],
    "quiz": [
        frage_mc(501, T1, "Choose the correct sentence.", ["She didn't went home.", "She didn't go home.", "She not went home.", "She don't go home."], 1,
                 "Nach *didn't* steht die Grundform."),
        frage_wf(502, T2, "In a formal letter you should use contractions like *I'm*.", False, "Formelle Briefe vermeiden Kurzformen."),
    ],
}

# ---------------------------------------------------------------- Wissen (Geographie)
T1 = "t-00000601"
FIXTURES["wissen"] = {
    "projekt": {"titel": "Klimazonen", "untertitel": "Geographie", "fach": "geographie"},
    "themen": [
        {"id": T1, "titel": "Klima Mitteleuropas", "kurz": "Gemäßigte Zone", "quelle": "foto", "bloecke": [
            {"id": "b-00000601", "typ": "definition", "quelle": "foto", "begriff": "Klima",
             "md": "Durchschnittlicher Zustand der Atmosphäre über mindestens 30 Jahre.", "spick": True},
            {"id": "b-00000602", "typ": "klimadiagramm", "quelle": "foto", "ort": "Wien", "lage": "48° N, 16° O, 171 m",
             "klima": "Gemäßigtes Klima",
             "temperatur": [0.3, 2.0, 6.0, 11.0, 15.7, 19.0, 21.0, 20.6, 16.0, 10.5, 5.2, 1.2],
             "niederschlag": [38, 42, 41, 51, 62, 70, 68, 58, 54, 40, 49, 44]},
            {"id": "b-00000603", "typ": "zeitleiste", "quelle": "ki", "titel": "Klimageschichte",
             "eintraege": [{"zeit": "um 1300", "titel": "Mittelalterliche Warmzeit endet"},
                           {"zeit": "1550–1850", "titel": "Kleine Eiszeit", "md": "Gletscher stoßen weit vor."},
                           {"zeit": "seit 1850", "titel": "Industrialisierung", "md": "Anstieg der CO₂-Konzentration."}]},
            {"id": "b-00000604", "typ": "diagramm", "quelle": "ki", "titel": "Projektplan Exkursion",
             "mermaid": "gantt\n  dateFormat YYYY-MM-DD\n  section Vorbereitung\n  Planung :a1, 2026-11-02, 5d\n  Exkursion :after a1, 1d"},
            {"id": "b-00000605", "typ": "klimadiagramm", "quelle": "ki", "ort": "Absichtlich falsch (Testfall)",
             "temperatur": [1, 2, 3], "niederschlag": [1, 2, 3]},
        ]},
    ],
    "aufgaben": [
        aufgabe(601, T1, "Jahresniederschlag", "Berechne den Jahresniederschlag von Wien aus dem Diagramm.",
                [("Summe", [txt(621, "Alle Monatswerte addieren.")])], "617 mm",
                {"art": "numerisch", "ausdruck": "38+42+41+51+62+70+68+58+54+40+49+44", "erwartet": 617, "toleranz": 0.5}),
    ],
    "karten": [karte(601, T1, "Wärmster Monat in Wien?", "Juli")],
    "quiz": [
        frage_mc(601, T1, "Wie lange wird Wetter mindestens gemittelt, um vom Klima zu sprechen?", ["30 Jahre", "1 Jahr", "10 Jahre", "100 Jahre"], 0,
                 "Klimanormalperioden umfassen 30 Jahre."),
        frage_wf(602, T1, "Wien hat im Juli mehr Niederschlag als im Jänner.", True, "Juli 68 mm, Jänner 38 mm."),
        frage_mc(603, T1, "Absichtlich falsch (Testfall)", ["A", "B"], 5, "Nur zwei Optionen und falscher Index."),
    ],
}


def main():
    for name, d in FIXTURES.items():
        doc = {"schema_version": 1, **d}
        doc["projekt"].setdefault("sprache", "de")
        ziel = HIER / name / "inhalt.json"
        ziel.parent.mkdir(exist_ok=True)
        ziel.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
        print("geschrieben:", ziel)


if __name__ == "__main__":
    main()
