"""Pipeline: Fotos → Transkript → Patch → Prüfen/Korrigieren → Rendern."""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, ValidationError

from . import bilder as bildmod
from .config import PAKET
from .modelle.base import Modell, ModellFehler, waehlen
from .patch import ersetzen, finden, patch_anwenden, patch_fehler
from .projekt import Projekt
from .pruefer import elemente, pruefe
from .render.renderer import rendern
from .schema import (Aufgabe, Dokument, FotoEintrag, Karte, Korrektur, NeuAufgabe, NeuBlock, NeuFrage,
                     NeuKarte, Patch, ki_schema)

from . import faecher

Log = Callable[..., None]


def prompt_laden(name: str, **werte) -> str:
    text = (PAKET / "prompts" / f"{name}.md").read_text()
    for k, v in werte.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


def fach_werte(fach: str) -> dict[str, str]:
    """Platzhalter, die jeder Prompt bekommt: Fachname, Fach-Hinweis, Profil-Regeln."""
    f = faecher.fach(fach)
    regeln = (PAKET / "prompts" / "profile" / f"{f.profil}.md").read_text()
    return {"fach": f.name, "fach_hinweis": f.hinweis, "profil_regeln": regeln,
            "profil_transkript": faecher.PROFILE[f.profil].transkript}


def _naechste_nr(p: Projekt, meta) -> int:
    vorhanden = [int(Path(f.datei).stem) for f in meta.fotos if Path(f.datei).stem.isdigit()]
    alle_nr = vorhanden + [int(x.stem.split("-")[0]) for x in p.fotos.glob("*.jpg") if x.stem.split("-")[0].isdigit()]
    alle_nr += [int(x.stem) for x in (p.fotos / "original").glob("*") if x.stem.isdigit()]
    return max(alle_nr, default=0)


def _bild_speichern(im, ziel: Path) -> None:
    from PIL import Image

    from .einlesen import auf_weiss
    im = auf_weiss(im)
    im.thumbnail((bildmod.MAX_SEITE, bildmod.MAX_SEITE), Image.LANCZOS)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    im.save(ziel, "JPEG", quality=88)


def dokument_transkript(nr: int, eingelesen, fotos: Path) -> str:
    """Speichert die Bilder eines Dokuments als <nr>-bNN.jpg und ersetzt die Platzhalter durch SKIZZE-Zeilen."""
    md = eingelesen.md
    for i, b in enumerate(eingelesen.bilder, 1):
        datei = f"{nr:03d}-b{i:02d}.jpg"
        _bild_speichern(b.bild, fotos / datei)
        beschr = (b.alt or "Abbildung aus dem Dokument").replace('"', "'")
        md = md.replace(f"[[BILD {i}]]", f'[[SKIZZE art=bild foto={datei} bbox=0,0,1,1 beschreibung="{beschr}"]]')
    return md


def fotos_hinzufuegen(p: Projekt, dateien: list[tuple[str, bytes]]) -> list[FotoEintrag]:
    """Fotos: Original speichern, vorbereiten (EXIF, 2000 px, JPEG). Dokumente: ohne KI einlesen; ihre Bilder
    werden Bilddateien, gescannte Seiten werden Fotos. Gibt alle neuen Einträge zurück."""
    from .einlesen import DOK_ENDUNGEN, EinleseFehler, einlesen

    meta = p.meta()
    nr = _naechste_nr(p, meta)
    neu = []
    for name, daten in dateien:
        endung = Path(name).suffix.lower()
        if endung in DOK_ENDUNGEN:
            try:
                e = einlesen(name, daten)
            except EinleseFehler as ex:
                raise ValueError(f"{name}: {ex}") from ex
            if e.md.strip():
                nr += 1
                (p.fotos / "original").mkdir(parents=True, exist_ok=True)
                (p.fotos / "original" / f"{nr:03d}{endung}").write_bytes(daten)
                eintrag = FotoEintrag(datei=f"{nr:03d}{endung}", original=name, status="transkribiert", art="dokument",
                                      hinweise=e.hinweise)
                p.transkript_speichern(eintrag.datei, dokument_transkript(nr, e, p.fotos))
                meta.fotos.append(eintrag)
                neu.append(eintrag)
            for k, seite in enumerate(e.scanseiten, 1):
                nr += 1
                _bild_speichern(seite, p.fotos / f"{nr:03d}.jpg")
                eintrag = FotoEintrag(datei=f"{nr:03d}.jpg", original=f"{name} (Seite {k})",
                                      hinweise=e.hinweise if not e.md.strip() and k == 1 else [])
                meta.fotos.append(eintrag)
                neu.append(eintrag)
            continue
        if endung not in bildmod.ENDUNGEN:
            raise ValueError(f"Dateityp {endung or '?'} wird nicht unterstützt ({name}). Möglich: Fotos (jpg, png, "
                             f"heic, webp) und Dateien (pdf, docx, pptx, html, md, txt)")
        nr += 1
        orig = p.fotos / "original" / f"{nr:03d}{endung}"
        orig.parent.mkdir(parents=True, exist_ok=True)
        orig.write_bytes(daten)
        ziel = p.fotos / f"{nr:03d}.jpg"
        try:
            bildmod.vorbereiten(orig, ziel)
        except Exception as e:
            orig.unlink(missing_ok=True)
            raise ValueError(f"{name} ist kein lesbares Bild ({e})") from e
        eintrag = FotoEintrag(datei=ziel.name, original=name)
        meta.fotos.append(eintrag)
        neu.append(eintrag)
    p.meta_speichern(meta)
    return neu


def _code_zaun_weg(text: str) -> str:
    m = re.fullmatch(r"\s*```(?:markdown|md)?\s*\n(.*?)\n```\s*", text, re.S)
    return m.group(1) if m else text


class Pipeline:
    def __init__(self, projekt: Projekt, log: Log | None = None, modell: Modell | None = None):
        self.p = projekt
        self._log = log or (lambda *a, **k: None)
        self._modell = modell

    # ---------------------------------------------------------------- Hilfen
    def log(self, text: str, **extra):
        self._log("log", text=text, **extra)

    @property
    def modell(self) -> Modell:
        if self._modell is None:
            self._modell = waehlen(self.p.meta().modell)
        return self._modell

    def foto_status(self, datei: str, status: str) -> None:
        m = self.p.meta()
        for f in m.fotos:
            if f.datei == datei:
                f.status = status
        self.p.meta_speichern(m)

    def _ki_text(self, schritt: str, prompt: str, bilder: list[Path]) -> str:
        t = time.time()
        try:
            antwort = self.modell.text(prompt, bilder)
        finally:
            dauer = round(time.time() - t, 1)
        self.p.log(schritt, {"modell": self.modell.name, "prompt": prompt, "bilder": [b.name for b in bilder],
                             "antwort": antwort, "dauer_s": dauer})
        self.log(f"{schritt}: Antwort nach {dauer} s")
        return antwort

    def _ki_json(self, schritt: str, prompt: str, modell_cls: type[BaseModel], bilder: list[Path],
                 extra: Callable[[BaseModel], list[str]] | None = None):
        """Ruft das Modell auf, validiert per Pydantic; bei Fehlern genau ein Wiederholungsversuch."""
        schema = ki_schema(modell_cls, self.p.meta().fach)
        p = prompt
        for versuch in (1, 2):
            t = time.time()
            roh, fehler = None, ""
            try:
                roh = self.modell.json(p, schema, bilder)
                obj = modell_cls.model_validate(roh)
                probleme = extra(obj) if extra else []
                if not probleme:
                    self.p.log(schritt, {"modell": self.modell.name, "versuch": versuch, "prompt": p,
                                         "antwort": roh, "dauer_s": round(time.time() - t, 1)})
                    self.log(f"{schritt}: Antwort nach {round(time.time() - t, 1)} s")
                    return obj
                fehler = "\n".join(probleme)
            except ValidationError as e:
                fehler = str(e)
            except ModellFehler as e:
                fehler = str(e)
                if "kein gültiges JSON" not in fehler:  # Verbindungs-/CLI-Fehler: nicht wiederholen
                    self.p.log(schritt, {"modell": self.modell.name, "versuch": versuch, "prompt": p, "fehler": fehler})
                    raise
            self.p.log(schritt, {"modell": self.modell.name, "versuch": versuch, "prompt": p, "antwort": roh,
                                 "fehler": fehler, "dauer_s": round(time.time() - t, 1)})
            self.log(f"{schritt}: Antwort ungültig ({fehler[:200]}) – neuer Versuch" if versuch == 1 else
                     f"{schritt}: Antwort wieder ungültig")
            p = (prompt + "\n\n## Deine letzte Antwort war ungültig\n\n" + fehler[:4000] +
                 "\n\nGib eine vollständige, korrigierte Antwort nach dem Schema.")
        raise ModellFehler(f"{schritt}: keine gültige Antwort nach 2 Versuchen: {fehler[:500]}")

    # ---------------------------------------------------------------- 2) Transkribieren
    def transkribieren(self, alle: bool = False, dateien: list[str] | None = None) -> list[str]:
        meta = self.p.meta()
        ziel = [f for f in meta.fotos if f.art == "foto" and ((dateien and f.datei in dateien) or
                (not dateien and (f.status == "hochgeladen" or (alle and f.status != "verarbeitet"))))]
        fertig = []
        for i, f in enumerate(ziel, 1):
            self._log("fortschritt", text=f"Transkribiere {f.datei} ({i}/{len(ziel)})", schritt=i, von=len(ziel))
            prompt = prompt_laden("transkribieren", **fach_werte(meta.fach))
            md = _code_zaun_weg(self._ki_text("transkribieren", prompt, [self.p.fotos / f.datei]))
            self.p.transkript_speichern(f.datei, md)
            self.foto_status(f.datei, "transkribiert")
            fertig.append(f.datei)
        return fertig

    # ---------------------------------------------------------------- 4–8) Generieren
    def _bestand(self, doc: Dokument) -> str:
        if not doc.themen:
            return "(noch leer – dies ist der erste Durchlauf)"
        z = []
        for t in doc.themen:
            z.append(f"- Thema `{t.id}`: {t.titel}")
            for b in t.bloecke:
                kurz = re.sub(r"\s+", " ", b.model_dump_json(include={"md", "tex", "begriff", "titel"}))[:70]
                z.append(f"  - Block `{b.id}` ({b.typ}): {kurz}")
            for a in doc.aufgaben:
                if a.thema_id == t.id:
                    z.append(f"  - Aufgabe ({a.art}): {a.titel}")
            n = sum(1 for k in doc.karten if k.thema_id == t.id)
            if n:
                z.append(f"  - {n} Karteikarten")
            n = sum(1 for q in doc.quiz if q.thema_id == t.id)
            if n:
                z.append(f"  - {n} Quizfragen")
        return "\n".join(z)

    def _transkripte(self, eintraege) -> tuple[str, list[Path]]:
        """Transkripte ohne abgewählte Abschnitte; dazu die Fotos mit Graph-Skizzen (als Bild mitschicken)."""
        from .einlesen import abschnitte_filtern
        teile, mit_graph = [], []
        for f in eintraege:
            md = abschnitte_filtern(self.p.transkript(f.datei), f.ausgeschlossen)
            teile.append(f"<!-- foto: {f.datei} -->\n{md}")
            if f.art == "foto" and "art=graph" in md:
                mit_graph.append(self.p.fotos / f.datei)
        return "\n\n".join(teile), mit_graph

    def generieren(self) -> dict:
        meta = self.p.meta()
        neue = [f for f in meta.fotos if f.status == "kontrolliert"]
        if not neue:
            raise ValueError("Keine kontrollierten Fotos oder Dateien zum Verarbeiten")
        z = self._anreichern(neue, "", f"Anreichern ({len(neue)} Foto(s)/Datei(en))")
        for f in neue:
            self.foto_status(f.datei, "verarbeitet")
        return z

    def ergaenzen(self, hinweis: str) -> dict:
        """Fehlende Inhalte nachliefern: gleiche (verarbeitete) Transkripte, Wunsch des Schülers, nur Neues."""
        meta = self.p.meta()
        quellen = [f for f in meta.fotos if f.status in ("verarbeitet", "kontrolliert")]
        if not quellen:
            raise ValueError("Es gibt noch keine verarbeiteten Fotos oder Dateien")
        if not hinweis.strip():
            raise ValueError("Bitte beschreiben, was fehlt")
        zusatz = ("## Auftrag: Ergänzen\n\nDie Seite existiert schon (siehe Bestand). Der Schüler vermisst Folgendes:\n\n"
                  f"> {hinweis.strip()}\n\nLiefere **nur** die fehlenden Inhalte aus den Transkripten: neue Themen oder "
                  "`neue_bloecke` in bestehende Themen, dazu passende Aufgaben, Karten und Quizfragen. Wiederhole nichts, "
                  "was im Bestand schon vorkommt. Gibt es dazu nichts in den Transkripten, ergänze es sinnvoll mit `quelle: \"ki\"`.")
        return self._anreichern(quellen, zusatz, "Ergänzen")

    def _anreichern(self, eintraege, zusatz: str, titel: str) -> dict:
        meta = self.p.meta()
        doc = self.p.inhalt()
        transkripte, mit_graph = self._transkripte(eintraege)
        e = meta.einstellungen
        prompt = prompt_laden(
            "anreichern", **fach_werte(meta.fach), transkripte=transkripte,
            bestand=self._bestand(doc), probeaufgaben_pro_thema=e.probeaufgaben_pro_thema,
            quiz_pro_thema=e.quiz_pro_thema, zusatz=zusatz,
            karten="auto" if e.karten == "auto" else f"{e.karten} je Thema", erklaerstil=e.erklaerstil)
        self._log("fortschritt", text=titel, schritt=1, von=3)
        patch = self._ki_json("anreichern", prompt, Patch, mit_graph, extra=lambda pt: patch_fehler(doc, pt))
        neu_ids = patch_anwenden(doc, patch)
        self.log(f"{len(neu_ids)} neue Elemente eingefügt")
        self.p.inhalt_speichern(doc)
        self._log("fortschritt", text="Prüfen und korrigieren", schritt=2, von=3)
        zusammenfassung = self.pruefen_korrigieren(doc, neu_ids, e.max_korrekturrunden)
        self._log("fortschritt", text="Seite bauen", schritt=3, von=3)
        self.bauen(doc)
        zusammenfassung["neu"] = len(neu_ids)
        return zusammenfassung

    def pruefen_korrigieren(self, doc: Dokument, ids: set[str], max_runden: int) -> dict:
        fotos = self.p.fotos
        ergebnis = pruefe(doc, ids, fotos)
        self._pruef_log(ergebnis)
        runde = 0
        while runde < max_runden:
            fehlerhaft = {i for i, pr in ergebnis.items() if pr.status == "fehler"}
            if not fehlerhaft:
                break
            runde += 1
            self.log(f"Korrekturrunde {runde}: {len(fehlerhaft)} Element(e)")
            try:
                k = self._korrektur(doc, fehlerhaft)
            except ModellFehler as e:
                self.log(f"Korrektur fehlgeschlagen: {e}")
                break
            ersetzt = set()
            for liste, feld in ((k.bloecke, "block"), (k.aufgaben, "aufgabe"), (k.karten, "karte"), (k.fragen, "frage")):
                for ers in liste:
                    if ers.id in fehlerhaft:
                        try:
                            ersetzen(doc, ers.id, getattr(ers, feld))
                            ersetzt.add(ers.id)
                        except (KeyError, ValueError) as ex:
                            self.log(f"Ersetzung {ers.id} verworfen: {ex}")
            self.p.inhalt_speichern(doc)
            if not ersetzt:
                self.log("Die KI hat keine verwertbaren Korrekturen geliefert")
                break
            neu = pruefe(doc, ersetzt, fotos, runde=runde)
            self._pruef_log(neu)
            ergebnis.update(neu)
        self.p.inhalt_speichern(doc)
        zaehl: dict[str, int] = {}
        for pr in ergebnis.values():
            zaehl[pr.status] = zaehl.get(pr.status, 0) + 1
        return {"status": zaehl, "runden": runde}

    def _pruef_log(self, ergebnis):
        for i, pr in sorted(ergebnis.items()):
            self._log("pruefung", id=i, status=pr.status, meldungen=pr.meldungen,
                      text=f"{i}: {pr.status}" + (f" – {pr.meldungen[0][:160]}" if pr.meldungen else ""))

    def _korrektur(self, doc: Dokument, ids: set[str]) -> Korrektur:
        teile = []
        themen = {t.id: t for t in doc.themen}
        for i in sorted(ids):
            art, el, _, thema = finden(doc, i)
            th = thema or themen.get(getattr(el, "thema_id", ""))
            js = el.model_dump_json(indent=1, exclude={"pruefung", "gesperrt", "id", "thema_id"})
            teile.append(f"### {art} `{i}`" + (f" (Thema: {th.titel})" if th else "") +
                         "\n\nMeldungen:\n" + "\n".join(f"- {m}" for m in el.pruefung.meldungen) +
                         f"\n\nAktuell:\n```json\n{js}\n```")
        meta = self.p.meta()
        prompt = prompt_laden("korrigieren", **fach_werte(meta.fach), fehler="\n\n".join(teile))
        return self._ki_json("korrigieren", prompt, Korrektur, [])

    # ---------------------------------------------------------------- Einzelnes Element neu
    def element_neu(self, id_: str, hinweis: str) -> dict:
        doc = self.p.inhalt()
        art, el, _, thema = finden(doc, id_)
        if art == "thema":
            raise ValueError("Themen können nicht neu generiert werden")
        th = thema or {t.id: t for t in doc.themen}.get(getattr(el, "thema_id", ""))
        kontext = f"Thema: {th.titel} – {th.kurz}" if th else "(kein Thema)"
        if th and art == "block":
            kontext += "\nAndere Blöcke dieses Themas: " + ", ".join(b.typ for b in th.bloecke if b.id != id_)
        meta = self.p.meta()
        js = el.model_dump_json(indent=1, exclude={"pruefung", "gesperrt", "id", "thema_id"})
        prompt = prompt_laden("block_neu", **fach_werte(meta.fach), element=js,
                              kontext=kontext, hinweis=hinweis or "(kein besonderer Wunsch – einfach besser machen)")
        cls, feld = {"block": (NeuBlock, "block"), "aufgabe": (NeuAufgabe, "aufgabe"), "karte": (NeuKarte, "karte"),
                     "frage": (NeuFrage, "frage")}[art]
        extra = (lambda o: [] if o.block.typ == el.typ else [f"typ muss {el.typ} bleiben"]) if art == "block" else None
        antwort = self._ki_json("block_neu", prompt, cls, [], extra=extra)
        ersetzen(doc, id_, getattr(antwort, feld))
        self.p.inhalt_speichern(doc)
        z = self.pruefen_korrigieren(doc, {id_}, meta.einstellungen.max_korrekturrunden)
        self.bauen(doc)
        return z

    # ---------------------------------------------------------------- Prüfen + Bauen ohne KI
    def pruefen_bauen(self, ids: set[str] | None = None) -> dict:
        doc = self.p.inhalt()
        ziel = ids if ids is not None else set(elemente(doc))
        ergebnis = pruefe(doc, ziel, self.p.fotos)
        self._pruef_log(ergebnis)
        self.p.inhalt_speichern(doc)
        self.bauen(doc)
        zaehl: dict[str, int] = {}
        for pr in ergebnis.values():
            zaehl[pr.status] = zaehl.get(pr.status, 0) + 1
        return {"status": zaehl}

    def bauen(self, doc: Dokument | None = None) -> dict:
        doc = doc or self.p.inhalt()
        info = rendern(doc, self.p.fotos, self.p.slug, self.p.ausgabe, self.p.ordner / "diagramme")
        m = self.p.meta()
        m.letzter_build = datetime.now().isoformat(timespec="seconds")
        self.p.meta_speichern(m)
        self.log(f"Seite gebaut: {info['log']}")
        if info["warnung"]:
            self.log("Warnung: Die Seite ist größer als 3 MB")
        return info


__all__ = ["Pipeline", "fotos_hinzufuegen", "prompt_laden", "json", "Aufgabe", "Karte"]
