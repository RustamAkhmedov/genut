"""Fächer und Fach-Profile.

Jedes Fach gehört zu genau einem Profil. Das Profil bestimmt die Prompt-Regeln, welche Blocktypen
und Prüfarten die KI im Schema angeboten bekommt, und die Akzentfarbe der Lernseite.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Profil:
    name: str
    bloecke: frozenset[str]          # zusätzlich zu GEMEINSAME_BLOECKE
    checks: frozenset[str] = field(default_factory=frozenset)
    transkript: str = ""             # Zusatzregel fürs Abschreiben


GEMEINSAME_BLOECKE = frozenset({"text", "definition", "regel", "tabelle", "bild", "hinweis", "diagramm"})

PROFILE: dict[str, Profil] = {
    "mathe_nw": Profil(
        "Mathematik & Naturwissenschaften",
        frozenset({"formel", "graph", "reaktion"}),
        frozenset({"gleich", "loesungen", "numerisch", "einheit", "reaktion"}),
        "Chemische Formeln und Reaktionsgleichungen schreibst du mit mhchem: `\\(\\ce{2H2 + O2 -> 2H2O}\\)`. "
        "Einheiten gehören zur Zahl (z. B. `\\(12\\,\\mathrm{m/s}\\)`). "
        "Gezeichnete Strukturformeln bekommen eine SKIZZE-Zeile (`art=bild`); nenne in der beschreibung das Molekül "
        "und die Halbstrukturformel, z. B. „Valenzstrichformel von Ethanol, CH3-CH2-OH“.",
    ),
    "programmieren": Profil(
        "Programmieren",
        frozenset({"code", "befehl"}),
        frozenset(),
        "Code schreibst du exakt mit Einrückung in einen Markdown-Codeblock mit Sprache (z. B. ```java). "
        "Nichts am Code verbessern, auch keine Tippfehler.",
    ),
    "datenbanken": Profil(
        "Datenbanken",
        frozenset({"code", "sql"}),
        frozenset({"sql"}),
        "SQL schreibst du exakt in einen Codeblock ```sql. Tabellen als Markdown-Tabellen.",
    ),
    "netzwerk": Profil(
        "Netzwerktechnik",
        frozenset({"befehl", "code", "subnetzrechner"}),
        frozenset({"subnetz", "numerisch"}),
        "Befehle und Konfigurationen (Cisco IOS, Linux) schreibst du exakt in einen Codeblock. "
        "IP-Adressen und Masken genau übernehmen.",
    ),
    "sprachen": Profil(
        "Sprachen",
        frozenset({"vokabel", "lueckentext", "textsorte", "werk"}),
        frozenset(),
        "Fremdsprachige Texte schreibst du in der Originalsprache ab, nicht übersetzen. "
        "Lücken in Übungen als `___`.",
    ),
    "wissen": Profil(
        "Wissen",
        frozenset({"zeitleiste", "klimadiagramm", "formel"}),
        frozenset({"numerisch", "gleich"}),
        "Diagramme (z. B. Klimadiagramme, Gantt) beschreibst du in der SKIZZE-Zeile mit allen ablesbaren Werten.",
    ),
}


@dataclass(frozen=True)
class Fach:
    name: str
    kurz: str
    profil: str
    hinweis: str = ""                # fachspezifischer Zusatz für den Anreichern-Prompt
    bloecke: frozenset[str] = frozenset()  # Blocktypen nur für dieses Fach (zusätzlich zum Profil)


FAECHER: dict[str, Fach] = {
    "mathe": Fach("Mathematik", "AM", "mathe_nw"),
    "physik": Fach("Physik", "Physik", "mathe_nw",
                   "Physikaufgaben bekommen einen Check `einheit`, damit Zahl **und** Einheit geprüft werden."),
    "chemie": Fach("Chemie", "Chemie", "mathe_nw",
                   "Reaktionsgleichungen als Block `reaktion` (mhchem-Syntax), Ausgleichsaufgaben mit Check `reaktion`. "
                   "Strukturformeln (Valenzstrich-, Skelettformel) immer als Block `struktur` mit SMILES – das Programm "
                   "zeichnet sie; niemals Strukturformeln als ASCII-Zeichnung, Code-Block, Tabelle oder Mermaid-Diagramm. "
                   "Halbstrukturformeln (Kurzschreibweise) im Text als `\\(\\ce{CH3-CH2-OH}\\)`, Doppel- und "
                   "Dreifachbindung als `=` und `#`.",
                   bloecke=frozenset({"struktur"})),
    "pos": Fach("Programmieren und Software Engineering", "POS", "programmieren",
                "Hauptsprache Java. Code-Beispiele in Java, außer das Foto zeigt etwas anderes."),
    "wmc": Fach("Web- und Mobile Computing", "WMC", "programmieren",
                "Sprachen: JavaScript/TypeScript, HTML, CSS."),
    "dsai": Fach("Data Science und Artificial Intelligence", "DSAI", "programmieren",
                 "Hauptsprache Python (numpy, pandas, scikit-learn, matplotlib)."),
    "dbi": Fach("Datenbanken und Informationssysteme", "DBI", "datenbanken"),
    "nscs": Fach("Netzwerksysteme und Cybersecurity", "NSCS", "netzwerk"),
    "englisch": Fach("Englisch", "E", "sprachen",
                     "Beispiele, Vokabeln, Texte und Quizfragen auf **Englisch**; Erklärungen, Regeln und Tipps auf **Deutsch**."),
    "deutsch": Fach("Deutsch", "D", "sprachen",
                    "Grammatik und Rechtschreibung mit Lückentexten; Textsorten als Block `textsorte`, Literatur als Block `werk`."),
    "geographie": Fach("Geographie", "GGP", "wissen"),
    "syp": Fach("Systemplanung und Projektentwicklung", "SYP", "wissen",
                "Projektmanagement-Diagramme (Gantt, Projektstrukturplan, Netzplan, UML) als Block `diagramm`."),
    "sonstiges": Fach("Allgemein", "–", "wissen"),
}

ALTE_FAECHER = {"netzwerk": "nscs"}  # Werte aus früheren Versionen


def fach(key: str) -> Fach:
    return FAECHER.get(ALTE_FAECHER.get(key, key), FAECHER["sonstiges"])


def profil_von(key: str) -> str:
    return fach(key).profil


def profil(key: str) -> Profil:
    return PROFILE[profil_von(key)]


def erlaubte_bloecke(key: str) -> frozenset[str]:
    return GEMEINSAME_BLOECKE | profil(key).bloecke | fach(key).bloecke


def liste() -> list[dict]:
    """Für die UI: Fächer gruppiert nach Profil."""
    return [{"key": k, "name": f.name, "kurz": f.kurz, "profil": f.profil, "profil_name": PROFILE[f.profil].name}
            for k, f in FAECHER.items()]
