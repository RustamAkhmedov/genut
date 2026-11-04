"""Datenmodell von inhalt.json und der KI-Antworten.

Felder, die nur der Server schreibt (id, gesperrt, pruefung, ausdruck_js, thema_id),
sind mit SkipJsonSchema markiert: Sie fehlen im Schema, das die KI bekommt.
"""
from __future__ import annotations

import copy
import json
from typing import Annotated, Literal, Union

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator
from pydantic.json_schema import SkipJsonSchema

Quelle = Literal["foto", "ki"]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Pruefung(_M):
    status: Literal["ok", "fehler", "ungeprueft", "nicht_pruefbar"]
    meldungen: list[str] = []
    runden: int = 0
    zeit: str = ""


# ---------------------------------------------------------------- Graph

class Funktion(_M):
    ausdruck: str = Field(description="SymPy-Syntax, Variable x und Parameternamen, z. B. a*x**2 + 1")
    label: str = ""
    ausdruck_js: SkipJsonSchema[str | None] = None


class Parameter(_M):
    name: str = Field(description="ein Buchstabe (nicht x, nicht e) oder Buchstabe_Ziffer, z. B. a oder k_1")
    min: float
    max: float
    schritt: float
    start: float
    bedeutung: str = ""


class Flaeche(_M):
    funktion: int = Field(0, description="Index in funktionen")
    von: float
    bis: float


class Graph(_M):
    x_min: float
    x_max: float
    y_min: float | None = None
    y_max: float | None = None
    funktionen: list[Funktion]
    parameter: list[Parameter] = []
    flaeche: Flaeche | None = None


# ---------------------------------------------------------------- Blöcke

class _Block(_M):
    id: SkipJsonSchema[str] = ""
    quelle: Quelle
    foto: str | None = Field(None, description="Dateiname des Fotos, wenn quelle == foto")
    spick: bool = Field(False, description="true = zusätzlich auf dem Spickzettel")
    gesperrt: SkipJsonSchema[bool] = False
    pruefung: SkipJsonSchema[Pruefung | None] = None


class Variable(_M):
    name: str = Field(description="TeX, z. B. s oder f'(x)")
    bedeutung: str


class TextBlock(_Block):
    typ: Literal["text"]
    md: str


class DefinitionBlock(_Block):
    typ: Literal["definition"]
    begriff: str
    md: str


class RegelBlock(_Block):
    typ: Literal["regel"]
    titel: str
    md: str
    beispiele: list[str] = []


class FormelBlock(_Block):
    typ: Literal["formel"]
    titel: str | None = None
    tex: str = Field(description="TeX ohne Begrenzer \\[ \\]")
    erklaerung_md: str | None = None
    variablen: list[Variable] = []
    graph: Graph | None = None


class GraphBlock(_Block):
    typ: Literal["graph"]
    titel: str | None = None
    graph: Graph
    erklaerung_md: str | None = None


class TabelleBlock(_Block):
    typ: Literal["tabelle"]
    titel: str | None = None
    kopf: list[str]
    zeilen: list[list[str]]


class BildBlock(_Block):
    typ: Literal["bild"]
    foto: str
    bbox: list[float] = Field(description="[x, y, breite, hoehe], relativ 0–1, Ursprung oben links")
    alt: str
    beschriftung: str | None = None


class HinweisBlock(_Block):
    typ: Literal["hinweis"]
    art: Literal["tipp", "falle"]
    md: str


class ZeilenErklaerung(_M):
    zeilen: str = Field(description="Zeilennummer oder Bereich, z. B. 3 oder 5-7 (ab 1 gezählt)")
    md: str


class CodeBlock(_Block):
    typ: Literal["code"]
    sprache: str
    code: str
    erklaerung_md: str | None = None
    erklaerungen: list[ZeilenErklaerung] = Field([], description="Erklärung Zeile für Zeile")


class BefehlBlock(_Block):
    typ: Literal["befehl"]
    befehl: str
    erklaerung_md: str
    kontext: str | None = None


class VokabelBlock(_Block):
    typ: Literal["vokabel"]
    wort: str
    uebersetzung: str
    beispiel: str | None = None


class ReaktionBlock(_Block):
    typ: Literal["reaktion"]
    titel: str | None = None
    gleichung: str = Field(description="mhchem-Syntax ohne \\ce{}, z. B. 2H2 + O2 -> 2H2O oder Fe^3+ + 3OH- -> Fe(OH)3")
    erklaerung_md: str | None = None
    ausgleichen: bool = Field(True, description="true = Atome und Ladung müssen ausgeglichen sein (wird geprüft)")


class StrukturBlock(_Block):
    typ: Literal["struktur"]
    name: str = Field(description="Name des Moleküls, z. B. Ethanol")
    smiles: str = Field(description="SMILES des Moleküls, z. B. CCO (Ethanol), CC(=O)O (Essigsäure), C/C=C\\C (cis-But-2-en), "
                                    "c1ccccc1 (Benzol). Daraus zeichnet das Programm die Strukturformel.")
    summenformel: str = Field(description="Summenformel in mhchem-Syntax ohne \\ce{}, z. B. C2H6O – wird gegen den SMILES geprüft")
    halbstruktur: str | None = Field(None, description="Halbstrukturformel (Kurzschreibweise) in mhchem-Syntax ohne \\ce{}, "
                                                         "Bindungen als - = #, z. B. CH3-CH2-OH")
    darstellung: Literal["valenzstrich", "skelett", "beide"] = Field(
        "beide", description="valenzstrich = alle Atome und Bindungen, skelett = Gerüstformel (Zickzack), beide = nebeneinander")
    erklaerung_md: str | None = None


class SqlErgebnis(_M):
    spalten: list[str] = []
    zeilen: list[list[str | int | float | None]] = []
    fehler: str | None = None


class SqlBlock(_Block):
    typ: Literal["sql"]
    titel: str | None = None
    aufgabe_md: str | None = Field(None, description="Fragestellung, wenn der Block eine Übung ist")
    schema_sql: str = Field(description="CREATE TABLE und INSERT mit kleinen Beispieldaten (SQLite-Dialekt)")
    abfrage: str = Field(description="die Abfrage bzw. Musterlösung (SQLite-Dialekt)")
    erklaerung_md: str | None = None
    ergebnis: SkipJsonSchema[SqlErgebnis | None] = None


class SubnetzrechnerBlock(_Block):
    typ: Literal["subnetzrechner"]
    titel: str | None = None
    start: str = Field("192.168.1.10/24", description="Startwert, Adresse mit Präfix (IPv4 oder IPv6)")
    erklaerung_md: str | None = None


class LueckentextBlock(_Block):
    typ: Literal["lueckentext"]
    titel: str | None = None
    anweisung_md: str | None = None
    text: str = Field(description="Markdown; jede Lücke als [[Lösung]], mehrere richtige Lösungen als [[Lösung|Alternative]]")


class TextsorteBlock(_Block):
    typ: Literal["textsorte"]
    name: str
    zweck_md: str | None = None
    aufbau: list[str] = Field(description="Gliederung, ein Punkt pro Teil (Markdown)")
    merkmale: list[str] = []
    formulierungen: list[str] = Field([], description="nützliche Formulierungen/Phrasen")
    beispiel_md: str | None = None


class WerkBlock(_Block):
    typ: Literal["werk"]
    titel: str
    autor: str
    jahr: str | None = None
    epoche: str | None = None
    gattung: str | None = None
    inhalt_md: str
    motive: list[str] = []
    zitat: str | None = None


class ZeitEintrag(_M):
    zeit: str = Field(description="z. B. 1914, 1918–1938 oder 3000 v. Chr.")
    titel: str
    md: str | None = None


class ZeitleisteBlock(_Block):
    typ: Literal["zeitleiste"]
    titel: str | None = None
    eintraege: list[ZeitEintrag]


class KlimadiagrammBlock(_Block):
    typ: Literal["klimadiagramm"]
    ort: str
    lage: str | None = Field(None, description="z. B. 48° N, 16° O, 171 m")
    klima: str | None = Field(None, description="Klimazone/Klimatyp")
    temperatur: list[float] = Field(description="12 Monatsmittel in °C, Jänner bis Dezember")
    niederschlag: list[float] = Field(description="12 Monatssummen in mm, Jänner bis Dezember")
    erklaerung_md: str | None = None


class DiagrammBlock(_Block):
    typ: Literal["diagramm"]
    titel: str | None = None
    mermaid: str = Field(description="Mermaid-Quelltext, z. B. classDiagram, erDiagram, gantt, flowchart TD, mindmap")
    erklaerung_md: str | None = None


Block = Annotated[
    Union[TextBlock, DefinitionBlock, RegelBlock, FormelBlock, GraphBlock, TabelleBlock,
          BildBlock, HinweisBlock, CodeBlock, BefehlBlock, VokabelBlock,
          ReaktionBlock, StrukturBlock, SqlBlock, SubnetzrechnerBlock, LueckentextBlock, TextsorteBlock, WerkBlock,
          ZeitleisteBlock, KlimadiagrammBlock, DiagrammBlock],
    Field(discriminator="typ"),
]


# ---------------------------------------------------------------- Aufgaben

class CheckGleich(_M):
    art: Literal["gleich"]
    ausdruck: str = Field(description="die Angabe selbst in SymPy, z. B. integrate(x**2, (x, 0, 2))")
    erwartet: str = Field(description="angegebenes Ergebnis in SymPy, z. B. 8/3")


class CheckLoesungen(_M):
    art: Literal["loesungen"]
    gleichungen: list[str] = Field(description='"x**2 - 4" bedeutet = 0, oder "Eq(links, rechts)"')
    variablen: list[str]
    erwartet: list[dict[str, str]] = Field(description='z. B. [{"x": "-2"}, {"x": "2"}]')


class CheckNumerisch(_M):
    art: Literal["numerisch"]
    ausdruck: str
    erwartet: float
    toleranz: float = 0.01


class CheckEinheit(_M):
    art: Literal["einheit"]
    ausdruck: str = Field(description="die Angabe mit Einheiten, z. B. 12*m/s * 3*s oder 90*km/h * 20*min")
    erwartet: str = Field(description="Ergebnis mit Einheit, z. B. 36*m")
    toleranz: float = Field(0.001, description="relative Toleranz, z. B. 0.01 bei auf 2–3 Stellen gerundeten Ergebnissen")


class CheckReaktion(_M):
    art: Literal["reaktion"]
    gleichung: str = Field(description="ausgeglichene Gleichung in mhchem-Syntax, z. B. 2H2 + O2 -> 2H2O")


class CheckSql(_M):
    art: Literal["sql"]
    schema_sql: str = Field(description="CREATE TABLE und INSERT (SQLite)")
    abfrage: str = Field(description="Musterlösung (SQLite)")
    erwartet: list[list[str]] = Field(description="erwartete Ergebniszeilen, jeder Wert als Text")
    reihenfolge: bool = Field(False, description="true = Zeilenreihenfolge muss stimmen (bei ORDER BY)")


class SubnetzWerte(_M):
    netzadresse: str | None = None
    broadcast: str | None = None
    erster_host: str | None = None
    letzter_host: str | None = None
    hosts: int | None = Field(None, description="Anzahl nutzbarer Hosts")
    maske: str | None = Field(None, description="Subnetzmaske in Punktnotation (nur IPv4)")
    praefix: int | None = None


class CheckSubnetz(_M):
    art: Literal["subnetz"]
    netz: str = Field(description="Adresse mit Präfix laut Angabe, z. B. 192.168.10.77/26 oder 2001:db8::1/64")
    erwartet: SubnetzWerte = Field(description="nur die Werte, nach denen die Aufgabe fragt")


Check = Annotated[Union[CheckGleich, CheckLoesungen, CheckNumerisch, CheckEinheit, CheckReaktion, CheckSql,
                        CheckSubnetz], Field(discriminator="art")]


class Ergebnis(_M):
    md: str
    check: Check | None = None


class Schritt(_M):
    titel: str
    quelle: Quelle
    bloecke: list[Block]


class Aufgabe(_M):
    id: SkipJsonSchema[str] = ""
    art: Literal["foto", "probe"] = Field(description="foto = vom Foto, probe = von der KI erzeugte Übungsaufgabe")
    quelle: Quelle
    foto: str | None = None
    thema_id: SkipJsonSchema[str] = ""
    titel: str
    schwierigkeit: int = Field(2, description="1 bis 3")
    angabe_md: str
    rechenaufgabe: bool = Field(False, description="true, wenn die Aufgabe ein eindeutiges, maschinell prüfbares "
                                "Ergebnis hat (Rechnung, Gleichung, SQL, Subnetz …) – dann ist ergebnis.check Pflicht")
    schritte: list[Schritt]
    ergebnis: Ergebnis
    gesperrt: SkipJsonSchema[bool] = False
    pruefung: SkipJsonSchema[Pruefung | None] = None


class Karte(_M):
    id: SkipJsonSchema[str] = ""
    thema_id: SkipJsonSchema[str] = ""
    quelle: Quelle
    vorne_md: str
    hinten_md: str
    gesperrt: SkipJsonSchema[bool] = False
    pruefung: SkipJsonSchema[Pruefung | None] = None


class Frage(_M):
    id: SkipJsonSchema[str] = ""
    thema_id: SkipJsonSchema[str] = ""
    quelle: Quelle
    art: Literal["mc", "wahrfalsch"] = Field(description="mc = 4 Antworten, eine richtig; wahrfalsch = Aussage beurteilen")
    frage_md: str = Field(description="Frage bzw. Aussage (Markdown, darf Codeblöcke enthalten)")
    optionen: list[str] = Field([], description="bei mc genau 4 Antwortmöglichkeiten, bei wahrfalsch leer")
    richtig: int | None = Field(None, description="bei mc: Index 0–3 der richtigen Option")
    wahr: bool | None = Field(None, description="bei wahrfalsch: ist die Aussage wahr?")
    erklaerung_md: str = Field(description="warum die Lösung stimmt (und warum die anderen nicht)")
    check: Check | None = Field(None, description="optional bei Rechenfragen; erwartet = Wert der richtigen Option")
    gesperrt: SkipJsonSchema[bool] = False
    pruefung: SkipJsonSchema[Pruefung | None] = None


# ---------------------------------------------------------------- Dokument

FACH = Literal["mathe", "physik", "chemie", "pos", "wmc", "dsai", "dbi", "nscs", "englisch", "deutsch",
               "geographie", "syp", "sonstiges"]


def _fach_alt(v):
    return {"netzwerk": "nscs"}.get(v, v)


FachFeld = Annotated[FACH, BeforeValidator(_fach_alt)]


class ProjektKopf(_M):
    titel: str
    untertitel: str = ""
    fach: FachFeld = "mathe"
    sprache: str = "de"


class Thema(_M):
    id: str
    titel: str
    kurz: str = ""
    quelle: Quelle
    bloecke: list[Block] = []


class Dokument(_M):
    schema_version: Literal[1] = 1
    projekt: ProjektKopf
    themen: list[Thema] = []
    aufgaben: list[Aufgabe] = []
    karten: list[Karte] = []
    quiz: list[Frage] = []


# ---------------------------------------------------------------- KI-Antworten

class PatchKopf(_M):
    titel: str
    untertitel: str = ""


class NeuesThema(_M):
    ref: str = Field(description="frei gewählte Kurzreferenz, z. B. T1")
    titel: str
    kurz: str = ""
    quelle: Quelle
    bloecke: list[Block] = []


class NeuerBlock(_M):
    thema_id: str = Field(description="ID eines BESTEHENDEN Themas")
    nach_block_id: str | None = Field(None, description="null = ans Ende des Themas")
    block: Block


class NeueAufgabe(Aufgabe):
    thema_ref: str = Field(description="ref aus neue_themen oder id eines bestehenden Themas")


class NeueKarte(Karte):
    thema_ref: str = Field(description="ref aus neue_themen oder id eines bestehenden Themas")


class NeueFrage(Frage):
    thema_ref: str = Field(description="ref aus neue_themen oder id eines bestehenden Themas")


class Patch(_M):
    projekt: PatchKopf | None = None
    neue_themen: list[NeuesThema] = []
    neue_bloecke: list[NeuerBlock] = []
    neue_aufgaben: list[NeueAufgabe] = []
    neue_karten: list[NeueKarte] = []
    neue_fragen: list[NeueFrage] = []


class BlockErsetzung(_M):
    id: str
    block: Block


class AufgabeErsetzung(_M):
    id: str
    aufgabe: Aufgabe


class KarteErsetzung(_M):
    id: str
    karte: Karte


class FrageErsetzung(_M):
    id: str
    frage: Frage


class Korrektur(_M):
    bloecke: list[BlockErsetzung] = []
    aufgaben: list[AufgabeErsetzung] = []
    karten: list[KarteErsetzung] = []
    fragen: list[FrageErsetzung] = []


class NeuBlock(_M):
    block: Block


class NeuAufgabe(_M):
    aufgabe: Aufgabe


class NeuKarte(_M):
    karte: Karte


class NeuFrage(_M):
    frage: Frage


# ---------------------------------------------------------------- Projekt-Metadaten

class Einstellungen(_M):
    probeaufgaben_pro_thema: int = Field(2, ge=0, le=5)
    karten: Literal["auto"] | int = "auto"
    max_korrekturrunden: int = Field(3, ge=0, le=5)
    erklaerstil: Literal["knapp", "ausfuehrlich"] = "knapp"
    quiz_pro_thema: int = Field(5, ge=0, le=10)


class FotoEintrag(_M):
    datei: str
    original: str
    status: Literal["hochgeladen", "transkribiert", "kontrolliert", "verarbeitet"] = "hochgeladen"
    art: Literal["foto", "dokument"] = "foto"      # dokument: Text ohne KI eingelesen (docx, pdf, …)
    ausgeschlossen: list[str] = []                 # abgewählte Überschriften (Themenauswahl)
    hinweise: list[str] = []                       # Hinweise beim Einlesen (z. B. Google-Docs-Ansicht)


class PagesStatus(_M):
    veroeffentlicht: bool = False
    zuletzt: str | None = None
    url: str | None = None


class ProjektMeta(_M):
    name: str
    slug: str
    fach: FachFeld = "mathe"
    modell: Literal["claude_code", "gemini", "ollama"] = "claude_code"
    einstellungen: Einstellungen = Einstellungen()
    fotos: list[FotoEintrag] = []
    pages: PagesStatus = PagesStatus()
    letzter_build: str | None = None

    @field_validator("modell", mode="before")
    @classmethod
    def _altes_modell(cls, v):
        return "gemini" if v == "grok" else v  # Grok gibt es nicht mehr


# ---------------------------------------------------------------- Schema für die KI

_WEG = {"discriminator", "title", "default", "minimum", "maximum", "exclusiveMinimum",
        "exclusiveMaximum", "minLength", "maxLength", "pattern", "minItems", "maxItems", "format"}


def _bereinigen(knoten):
    if isinstance(knoten, dict):
        neu = {}
        for k, v in knoten.items():
            if k in _WEG and not (k == "title" and isinstance(v, dict)):
                continue
            if k == "properties":
                neu[k] = {name: _bereinigen(s) for name, s in v.items()}
                continue
            if k == "oneOf":
                k = "anyOf"
            neu[k] = _bereinigen(v)
        if neu.get("type") == "object" and "properties" in neu:
            neu["additionalProperties"] = False
        return neu
    if isinstance(knoten, list):
        return [_bereinigen(x) for x in knoten]
    return knoten


def _const(defn: dict, feld: str) -> str | None:
    p = defn.get("properties", {}).get(feld, {})
    return p.get("const") or (p.get("enum") or [None])[0]


def _filtern(schema: dict, bloecke: set[str], checks: set[str]) -> dict:
    """Entfernt Blocktypen und Check-Arten, die das Fach-Profil nicht vorsieht, aus allen anyOf-Listen
    und danach alle nicht mehr erreichbaren $defs."""
    defs = schema.get("$defs", {})
    weg = set()
    for name, d in defs.items():
        if name.endswith("Block") and _const(d, "typ") and _const(d, "typ") not in bloecke:
            weg.add(name)
        if name.startswith("Check") and _const(d, "art") and _const(d, "art") not in checks:
            weg.add(name)

    def gehen(k):
        if isinstance(k, dict):
            for schl in ("anyOf", "oneOf"):  # diskriminierte Unions erzeugt Pydantic als oneOf
                if schl in k:
                    k[schl] = [x for x in k[schl] if not (isinstance(x, dict) and x.get("$ref", "").split("/")[-1] in weg)]
            if isinstance(k.get("discriminator"), dict):
                k["discriminator"]["mapping"] = {w: r for w, r in k["discriminator"].get("mapping", {}).items()
                                                 if r.split("/")[-1] not in weg}
            for v in k.values():
                gehen(v)
        elif isinstance(k, list):
            for v in k:
                gehen(v)

    gehen(schema)
    for n in weg:
        defs.pop(n, None)
    _leere_unions_entfernen(schema)
    # nicht mehr referenzierte Definitionen entfernen
    while True:
        text = json.dumps({k: v for k, v in schema.items() if k != "$defs"}) + json.dumps(defs)
        unbenutzt = [n for n in defs if f'"#/$defs/{n}"' not in text]
        if not unbenutzt:
            break
        for n in unbenutzt:
            defs.pop(n)
    return schema


def _leer(k) -> bool:
    return isinstance(k, dict) and any(k.get(x) == [] for x in ("anyOf", "oneOf"))


def _leere_unions_entfernen(k) -> None:
    """Nach dem Filtern: Union-Zweige ohne Alternative entfernen (z. B. Check-Union in Fächern ohne Check-Arten).
    Leere anyOf/oneOf sind ungültiges JSON-Schema; ein Feld ohne verbleibende Alternative fällt ganz weg."""
    if isinstance(k, list):
        for x in k:
            _leere_unions_entfernen(x)
        return
    if not isinstance(k, dict):
        return
    for v in list(k.values()):
        _leere_unions_entfernen(v)
    for schl in ("anyOf", "oneOf"):
        if isinstance(k.get(schl), list):
            k[schl] = [x for x in k[schl] if not _leer(x)]
    if isinstance(k.get("properties"), dict):
        for name in [n for n, v in k["properties"].items() if _leer(v)]:
            del k["properties"][name]
            if name in k.get("required", []):
                k["required"].remove(name)
    if isinstance(k.get("items"), dict) and _leer(k["items"]):
        k["items"] = {"oneOf": []}  # bleibt leer → Elternfeld wird entfernt


def ki_schema(modell: type[BaseModel], fach: str | None = None) -> dict:
    """JSON-Schema ohne Server-Felder und ohne Schlüsselwörter, die Structured-Output-Modi oft ablehnen.
    Mit fach: nur die Blocktypen und Check-Arten des Fach-Profils."""
    schema = copy.deepcopy(modell.model_json_schema())
    if fach is not None:
        from .faecher import erlaubte_bloecke, profil
        schema = _filtern(schema, set(erlaubte_bloecke(fach)), set(profil(fach).checks))
    return _bereinigen(schema)
