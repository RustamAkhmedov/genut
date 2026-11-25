"""Lokaler FastAPI-Server: Web-UI + API."""
from __future__ import annotations

import asyncio
import json
import re
import threading
import traceback
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from . import faecher
from . import formelsammlung
from . import funktionen
from . import export
from . import gruppen
from . import projektliste
from . import themen as themen_umfang
from .config import WURZEL, config_pfad, laden, wert_setzen
from .modelle.base import ModellFehler, waehlen
from .patch import finden, ids_vergeben, loeschen
from .pipeline import Pipeline, fotos_hinzufuegen
from .projekt import Projekt
from .pruefer import elemente
from .render.renderer import diagramm_hash
from .schema import Dokument, Einstellungen, ProjektMeta

app = FastAPI(title="gen_Ut", docs_url="/api/docs", redoc_url=None)
UI = WURZEL / "ui"
UI_STAND = 3  # steht auch in ui/index.html; nur nötig, um einmal alte Einträge im Browser-Cache zu umgehen
MATHJAX = WURZEL / "node_modules" / "mathjax-full" / "es5" / "tex-svg-full.js"


# ---------------------------------------------------------------- Hilfen

def projekt(slug: str) -> Projekt:
    try:
        return Projekt.laden(slug)
    except FileNotFoundError:
        raise HTTPException(404, f"Projekt {slug} nicht gefunden")


def uebersicht(p: Projekt) -> dict:
    m = p.meta()
    d = m.model_dump()
    d["hat_seite"] = p.ausgabe.exists()
    d["laeuft"] = JOBS.laufend(p.slug)
    if p.hat_inhalt():
        doc = p.inhalt()
        d["zahlen"] = {"themen": len(doc.themen), "aufgaben": len(doc.aufgaben), "karten": len(doc.karten),
                       "quiz": len(doc.quiz)}
    return d


# ---------------------------------------------------------------- Jobs

class Job:
    def __init__(self, slug: str, art: str):
        self.id = uuid.uuid4().hex[:12]
        self.slug, self.art = slug, art
        self.events: list[dict] = []
        self.fertig = False
        self.bedingung = threading.Condition()

    def emit(self, typ: str, **daten):
        with self.bedingung:
            self.events.append({"typ": typ, **daten})
            self.bedingung.notify_all()


class Jobs:
    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self.sperre = threading.Lock()

    def laufend(self, slug: str) -> str | None:
        return next((j.id for j in self.jobs.values() if j.slug == slug and not j.fertig), None)

    def starten(self, slug: str, art: str, fn) -> Job:
        with self.sperre:
            if self.laufend(slug):
                raise HTTPException(409, "Für dieses Projekt läuft bereits ein Auftrag")
            job = Job(slug, art)
            self.jobs[job.id] = job

        def ziel():
            try:
                ergebnis = fn(job)
                job.emit("fertig", ergebnis=ergebnis, text="Fertig")
            except (ModellFehler, ValueError, export.ExportFehler) as e:
                job.emit("fehler", text=str(e))
            except Exception as e:  # noqa: BLE001
                job.emit("fehler", text=f"{type(e).__name__}: {e}", trace=traceback.format_exc()[-2000:])
            finally:
                job.fertig = True
                with job.bedingung:
                    job.bedingung.notify_all()

        threading.Thread(target=ziel, daemon=True).start()
        return job


JOBS = Jobs()


# ---------------------------------------------------------------- UI

@app.get("/")
def start():
    return RedirectResponse(f"/ui/?v={UI_STAND}")


funktionen.einhaengen_alle(app)  # Module vor den statischen Routen


@app.get("/api/projekte/{slug}/themen")
def projekt_themen(slug: str):
    """Themen mit Umfang (gemeinsam für Lernplaner und Prüfung, unabhängig vom Funktionsschalter)."""
    p = projekt(slug)
    if not p.hat_inhalt():
        return []
    doc = p.inhalt()
    return [{"id": t.id, "titel": t.titel, "kurz": t.kurz, "umfang": themen_umfang.last(t, doc)} for t in doc.themen]


class _Oberflaeche(StaticFiles):
    """Nach einem Update darf der Browser keine alte Datei ungeprüft weiterverwenden (eine alte index.html zum
    neuen app.js zeigte eine leere Projektliste). Ohne Änderung bleibt es bei einem kurzen 304."""

    def file_response(self, *args, **kwargs):
        antwort = super().file_response(*args, **kwargs)
        antwort.headers["Cache-Control"] = "no-cache"
        return antwort


app.mount("/ui", _Oberflaeche(directory=UI, html=True), name="ui")


MERMAID = WURZEL / "node_modules" / "mermaid" / "dist" / "mermaid.min.js"


@app.get("/mermaid.js")
def mermaid_js():
    if not MERMAID.exists():
        raise HTTPException(404, "npm install fehlt (mermaid)")
    return FileResponse(MERMAID, media_type="text/javascript")


# ---------------------------------------------------------------- Diagramme (Mermaid → SVG in der Tool-Vorschau)

def _diagramme(doc) -> dict[str, str]:
    """hash → Mermaid-Quelltext aller diagramm-Blöcke."""
    bloecke = [b for t in doc.themen for b in t.bloecke] + [b for a in doc.aufgaben for s in a.schritte for b in s.bloecke]
    return {diagramm_hash(b.mermaid): b.mermaid for b in bloecke if b.typ == "diagramm"}


_SVG_BOESE = re.compile(r"<script\b.*?</script\s*>|\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)|javascript:", re.S | re.I)


def svg_bereinigen(svg: str) -> str:
    svg = svg.strip()
    if not svg.startswith("<svg") or not svg.endswith("</svg>") or len(svg) > 2_000_000:
        raise HTTPException(400, "kein gültiges SVG")
    return _SVG_BOESE.sub("", svg)


@app.get("/api/projekte/{slug}/diagramme/offen")
def diagramme_offen(slug: str):
    p = projekt(slug)
    ordner = p.ordner / "diagramme"
    return [{"hash": h, "quelle": q} for h, q in _diagramme(p.inhalt()).items()
            if not (ordner / f"{h}-hell.svg").exists() and not (ordner / f"{h}.fehler").exists()]


class DiagrammSvg(BaseModel):
    hell: str | None = None
    dunkel: str | None = None
    fehler: str | None = None


@app.put("/api/projekte/{slug}/diagramme/{h}")
def diagramm_speichern(slug: str, h: str, daten: DiagrammSvg):
    p = projekt(slug)
    if h not in _diagramme(p.inhalt()):
        raise HTTPException(404, "Diagramm gibt es in diesem Projekt nicht")
    ordner = p.ordner / "diagramme"
    ordner.mkdir(exist_ok=True)
    if daten.fehler:
        (ordner / f"{h}.fehler").write_text(daten.fehler[:2000], encoding="utf-8")
        return {"ok": True}
    if not daten.hell:
        raise HTTPException(400, "hell fehlt")
    (ordner / f"{h}-hell.svg").write_text(svg_bereinigen(daten.hell), encoding="utf-8")
    if daten.dunkel:
        (ordner / f"{h}-dunkel.svg").write_text(svg_bereinigen(daten.dunkel), encoding="utf-8")
    return {"ok": True}


@app.post("/api/projekte/{slug}/neu_bauen")
def neu_bauen(slug: str):
    """Nur rendern (ohne KI, ohne Prüfung), z. B. nachdem Diagramme gezeichnet wurden."""
    p = projekt(slug)
    if not p.inhalt_pfad.exists():
        raise HTTPException(400, "Noch kein Inhalt")
    return Pipeline(p).bauen()


# ---------------------------------------------------------------- Formelsammlung

class FormelEintraege(BaseModel):
    eintraege: list[formelsammlung.AuswahlEintrag] = []


def _formel_fehler(e: Exception) -> HTTPException:
    if isinstance(e, formelsammlung.UnbekannteFormel):
        return HTTPException(400, f"Unbekannte Formel: {e}. Es gibt keinen Formel-Block mit dieser Kennung.")
    if isinstance(e, formelsammlung.KeineFormelGewaehlt):
        return HTTPException(400, "Keine Formel gewählt. Wähle mindestens eine Formel aus.")
    if isinstance(e, formelsammlung.ErstellungLaeuft):
        return HTTPException(409, "Die Formelsammlung wird für dieses Projekt gerade erstellt.")
    return HTTPException(500, f"PDF konnte nicht erstellt werden: {e}")


@app.get("/api/projekte/{slug}/formeln")
def formeln_liste(slug: str):
    p = projekt(slug)
    if not p.hat_inhalt():
        return {"themen": [], "auswahl": [], "pdf": None}
    themen: dict[str, dict] = {}
    alle = formelsammlung.formeln(p.inhalt())
    vorhanden = {f["id"] for f in alle}  # gelöschte Formeln stehen nicht mehr in der Auswahl
    for f in alle:
        t = themen.setdefault(f["thema_id"], {"id": f["thema_id"], "titel": f["thema"], "formeln": []})
        t["formeln"].append({
            "id": f["id"], "titel": f["titel"], "tex": f["tex"], "variablen": f["variablen"],
            "hat_erklaerung": bool((f["erklaerung_md"] or "").strip()), "erklaerung_md": f["erklaerung_md"],
            "spick": f["spick"], "pruefung": f["pruefung"],
        })
    a = formelsammlung.auswahl_laden(p)
    return {"themen": list(themen.values()),
            "auswahl": [e.model_dump() for e in a.eintraege if e.block_id in vorhanden],
            "pdf": formelsammlung.pdf_info(p)}


@app.put("/api/projekte/{slug}/formelauswahl")
def formelauswahl_speichern(slug: str, daten: FormelEintraege):
    p = projekt(slug)
    if not p.hat_inhalt():
        raise HTTPException(400, "Noch kein Inhalt")
    try:
        a = formelsammlung.auswahl_speichern(p, daten.eintraege)
    except formelsammlung.UnbekannteFormel as e:
        raise _formel_fehler(e)
    return {"ok": True, "gespeichert": len(a.eintraege)}


@app.post("/api/projekte/{slug}/formelsammlung")
async def formelsammlung_erstellen(slug: str, daten: FormelEintraege | None = None):
    p = projekt(slug)
    if not p.hat_inhalt():
        raise HTTPException(400, "Noch kein Inhalt")
    eintraege = daten.eintraege if daten is not None else None
    try:
        return await asyncio.to_thread(formelsammlung.erzeugen, p, eintraege)
    except (formelsammlung.UnbekannteFormel, formelsammlung.KeineFormelGewaehlt,
            formelsammlung.ErstellungLaeuft, formelsammlung.PdfFehler) as e:
        raise _formel_fehler(e)


@app.get("/api/projekte/{slug}/formelsammlung.pdf")
def formelsammlung_pdf(slug: str):
    p = projekt(slug)
    pfad = formelsammlung.pdf_pfad(p)
    if not pfad.exists():
        raise HTTPException(404, "Die Formelsammlung wurde noch nicht erstellt")
    return FileResponse(pfad, media_type="application/pdf", filename=f"formelsammlung-{slug}.pdf",
                        content_disposition_type="attachment")


@app.get("/mathjax.js")
def mathjax():
    if not MATHJAX.exists():
        raise HTTPException(404, "npm install fehlt")
    return FileResponse(MATHJAX, media_type="text/javascript")


# ---------------------------------------------------------------- Projekte

class NeuesProjekt(BaseModel):
    name: str
    fach: str = "mathe"
    modell: str | None = None
    einstellungen: Einstellungen = Einstellungen()


class GruppeDaten(BaseModel):
    name: str


def _gruppe_antwort(g: dict) -> dict:
    anzahl = 0
    for p in Projekt.alle():
        try:
            if p.meta().gruppe == g["id"]:
                anzahl += 1
        except Exception:
            continue
    return {"id": str(g["id"]), "name": str(g["name"]), "anzahl": anzahl}


def _gruppe_fehler(e: Exception) -> HTTPException:
    if isinstance(e, gruppen.NameFehler):
        return HTTPException(400, str(e))
    if isinstance(e, gruppen.NameVergeben):
        return HTTPException(409, "Eine Gruppe mit diesem Namen gibt es schon.")
    return HTTPException(404, "Gruppe nicht gefunden")


@app.get("/api/gruppen")
def gruppen_liste():
    return sorted((_gruppe_antwort(g) for g in gruppen.laden()), key=lambda g: g["name"].casefold())


@app.post("/api/gruppen")
def gruppe_neu(daten: GruppeDaten):
    try:
        return _gruppe_antwort(gruppen.anlegen(daten.name))
    except (gruppen.NameFehler, gruppen.NameVergeben) as e:
        raise _gruppe_fehler(e)


@app.patch("/api/gruppen/{id_}")
def gruppe_aendern(id_: str, daten: GruppeDaten):
    try:
        return _gruppe_antwort(gruppen.umbenennen(id_, daten.name))
    except (gruppen.NameFehler, gruppen.NameVergeben, gruppen.GruppeUnbekannt) as e:
        raise _gruppe_fehler(e)


@app.delete("/api/gruppen/{id_}")
def gruppe_loeschen(id_: str):
    try:
        return {"ok": True, "verschoben": gruppen.loeschen(id_)}
    except gruppen.GruppeUnbekannt as e:
        raise _gruppe_fehler(e)


@app.get("/api/projekte")
def projekte():
    return [uebersicht(p) for p in Projekt.alle()]


@app.get("/api/projektliste")
def projektliste_abfrage(modus: str = "gruppen", sortierung: str = "gebaut"):
    try:
        return {"abschnitte": projektliste.abschnitte([uebersicht(p) for p in Projekt.alle()], modus, sortierung)}
    except ValueError:
        raise HTTPException(400, "Ungültiger Modus oder ungültige Sortierung")


@app.post("/api/projekte")
def projekt_neu(daten: NeuesProjekt):
    if not daten.name.strip():
        raise HTTPException(400, "Name fehlt")
    if daten.fach not in faecher.FAECHER:
        raise HTTPException(400, f"Unbekanntes Fach {daten.fach!r}")
    modell = daten.modell or laden()["modell"]["standard"]
    p = Projekt.anlegen(daten.name.strip(), fach=daten.fach, modell=modell, einstellungen=daten.einstellungen)
    return uebersicht(p)


@app.get("/api/projekte/{slug}")
def projekt_lesen(slug: str):
    return uebersicht(projekt(slug))


class ProjektAenderung(BaseModel):
    name: str | None = None
    modell: str | None = None
    einstellungen: Einstellungen | None = None
    gruppe: str | None = None  # "" = lösen, None = nicht ändern


@app.patch("/api/projekte/{slug}")
def projekt_aendern(slug: str, daten: ProjektAenderung):
    p = projekt(slug)
    m = p.meta()
    roh = m.model_dump()
    for k, v in daten.model_dump(exclude_none=True).items():
        if k == "gruppe":
            if v == "":
                v = None
            elif not gruppen.existiert(v):
                raise HTTPException(400, "Unbekannte Gruppe")
        roh[k] = v
    try:
        p.meta_speichern(ProjektMeta.model_validate(roh))
    except ValidationError as e:
        raise HTTPException(400, str(e))
    return uebersicht(p)


@app.delete("/api/projekte/{slug}")
def projekt_loeschen(slug: str):
    p = projekt(slug)
    if JOBS.laufend(slug):
        raise HTTPException(409, "Auftrag läuft noch")
    p.loeschen()
    return {"ok": True}


# ---------------------------------------------------------------- Fotos

@app.post("/api/projekte/{slug}/fotos")
async def fotos_hoch(slug: str, dateien: list[UploadFile] = File(...)):
    p = projekt(slug)
    daten = [(d.filename or "foto.jpg", await d.read()) for d in dateien]
    try:
        neu = await asyncio.to_thread(fotos_hinzufuegen, p, daten)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"neu": [f.model_dump() for f in neu], "projekt": uebersicht(p)}


class Reihenfolge(BaseModel):
    reihenfolge: list[str]


@app.patch("/api/projekte/{slug}/fotos")
def fotos_sortieren(slug: str, daten: Reihenfolge):
    p = projekt(slug)
    m = p.meta()
    nach_name = {f.datei: f for f in m.fotos}
    if sorted(daten.reihenfolge) != sorted(nach_name):
        raise HTTPException(400, "Reihenfolge muss alle Fotos genau einmal enthalten")
    m.fotos = [nach_name[d] for d in daten.reihenfolge]
    p.meta_speichern(m)
    return uebersicht(p)


@app.delete("/api/projekte/{slug}/fotos/{datei}")
def foto_loeschen(slug: str, datei: str):
    p = projekt(slug)
    m = p.meta()
    f = next((f for f in m.fotos if f.datei == datei), None)
    if f is None:
        raise HTTPException(404, "Foto nicht gefunden")
    if f.status == "verarbeitet":
        raise HTTPException(400, "Verarbeitete Fotos können nicht mehr gelöscht werden")
    m.fotos.remove(f)
    p.meta_speichern(m)
    (p.fotos / datei).unlink(missing_ok=True)
    p.transkript_pfad(datei).unlink(missing_ok=True)
    if f.art == "dokument":
        stamm = Path(datei).stem
        (p.fotos / "original" / datei).unlink(missing_ok=True)
        for b in p.fotos.glob(f"{stamm}-b*.jpg"):
            b.unlink()
    return uebersicht(p)


@app.get("/api/projekte/{slug}/fotos/{datei}")
def foto(slug: str, datei: str):
    p = projekt(slug)
    pfad = (p.fotos / datei).resolve()
    if pfad.parent != p.fotos.resolve() or not pfad.exists():
        raise HTTPException(404)
    return FileResponse(pfad)


# ---------------------------------------------------------------- Transkripte

class TranskriptDaten(BaseModel):
    md: str
    kontrolliert: bool = False
    ausgeschlossen: list[str] | None = None


@app.get("/api/projekte/{slug}/transkripte/{datei}")
def transkript(slug: str, datei: str):
    from .einlesen import ueberschriften
    p = projekt(slug)
    f = next((f for f in p.meta().fotos if f.datei == datei), None)
    if f is None:
        raise HTTPException(404)
    md = p.transkript(datei)
    bilder = sorted(b.name for b in p.fotos.glob(f"{Path(datei).stem}-b*.jpg")) if f.art == "dokument" else []
    return {"md": md, "status": f.status, "art": f.art, "original": f.original, "ausgeschlossen": f.ausgeschlossen,
            "hinweise": f.hinweise, "ueberschriften": ueberschriften(md), "bilder": bilder}


@app.post("/api/projekte/{slug}/dokumente/{datei}/neu_einlesen")
def dokument_neu_einlesen(slug: str, datei: str):
    from .einlesen import EinleseFehler, einlesen
    from .pipeline import dokument_transkript
    p = projekt(slug)
    m = p.meta()
    f = next((f for f in m.fotos if f.datei == datei and f.art == "dokument"), None)
    if f is None:
        raise HTTPException(404, "Dokument nicht gefunden")
    if f.status == "verarbeitet":
        raise HTTPException(400, "Schon verarbeitet")
    orig = p.fotos / "original" / datei
    try:
        e = einlesen(f.original, orig.read_bytes())
    except (EinleseFehler, OSError) as ex:
        raise HTTPException(400, str(ex))
    for b in p.fotos.glob(f"{Path(datei).stem}-b*.jpg"):
        b.unlink()
    p.transkript_speichern(datei, dokument_transkript(int(Path(datei).stem), e, p.fotos))
    f.status, f.ausgeschlossen, f.hinweise = "transkribiert", [], e.hinweise
    p.meta_speichern(m)
    return {"ok": True}


@app.put("/api/projekte/{slug}/transkripte/{datei}")
def transkript_speichern(slug: str, datei: str, daten: TranskriptDaten):
    p = projekt(slug)
    m = p.meta()
    f = next((f for f in m.fotos if f.datei == datei), None)
    if f is None:
        raise HTTPException(404)
    if f.status == "verarbeitet":
        raise HTTPException(400, "Foto ist schon verarbeitet; Änderungen wirken nicht mehr")
    p.transkript_speichern(datei, daten.md)
    f.status = "kontrolliert" if daten.kontrolliert else "transkribiert"
    if daten.ausgeschlossen is not None:
        f.ausgeschlossen = daten.ausgeschlossen
    p.meta_speichern(m)
    return {"ok": True, "status": f.status}


# ---------------------------------------------------------------- Jobs

class JobAuftrag(BaseModel):
    art: str
    dateien: list[str] | None = None
    id: str | None = None
    hinweis: str = ""


@app.post("/api/projekte/{slug}/jobs")
def job_starten(slug: str, auftrag: JobAuftrag):
    p = projekt(slug)

    def pl(job: Job) -> Pipeline:
        return Pipeline(p, log=job.emit)

    if auftrag.art == "transkribieren":
        fn = lambda job: {"dateien": pl(job).transkribieren(dateien=auftrag.dateien)}  # noqa: E731
    elif auftrag.art == "generieren":
        fn = lambda job: pl(job).generieren()  # noqa: E731
    elif auftrag.art == "block_neu":
        if not auftrag.id:
            raise HTTPException(400, "id fehlt")
        fn = lambda job: pl(job).element_neu(auftrag.id, auftrag.hinweis)  # noqa: E731
    elif auftrag.art == "pruefen_bauen":
        fn = lambda job: pl(job).pruefen_bauen()  # noqa: E731
    elif auftrag.art == "ergaenzen":
        if not (auftrag.hinweis or "").strip():
            raise HTTPException(400, "Bitte beschreiben, was fehlt")
        fn = lambda job: pl(job).ergaenzen(auftrag.hinweis)  # noqa: E731
    else:
        raise HTTPException(400, f"unbekannte Auftragsart {auftrag.art}")
    job = JOBS.starten(slug, auftrag.art, fn)
    return {"job_id": job.id}


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request):
    job = JOBS.jobs.get(job_id)
    if job is None:
        raise HTTPException(404)

    def warten(i: int):
        with job.bedingung:
            job.bedingung.wait_for(lambda: len(job.events) > i or job.fertig, timeout=15)
            return job.events[i:], job.fertig

    async def strom():
        i = 0
        while True:
            if await request.is_disconnected():
                return
            neu, fertig = await asyncio.to_thread(warten, i)
            for e in neu:
                yield f"data: {json.dumps(e, ensure_ascii=False, default=str)}\n\n"
            i += len(neu)
            if fertig and i >= len(job.events):
                return
            if not neu:
                yield ": ping\n\n"

    return StreamingResponse(strom(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


# ---------------------------------------------------------------- Inhalt

@app.get("/api/projekte/{slug}/inhalt")
def inhalt(slug: str):
    p = projekt(slug)
    return json.loads(p.inhalt().model_dump_json())


@app.put("/api/projekte/{slug}/inhalt")
async def inhalt_speichern(slug: str, request: Request):
    p = projekt(slug)
    if JOBS.laufend(slug):
        raise HTTPException(409, "Auftrag läuft noch")
    try:
        roh = json.loads(await request.body())
        neu = Dokument.model_validate(roh)
    except json.JSONDecodeError as e:
        raise HTTPException(400, {"fehler": [f"Kein gültiges JSON: {e}"]})
    except ValidationError as e:
        raise HTTPException(400, {"fehler": [f"{'.'.join(str(x) for x in f['loc'])}: {f['msg']}" for f in e.errors()]})

    def speichern():
        alt = elemente(p.inhalt())
        ids_vergeben(neu)
        geaendert = set()
        for i, el in elemente(neu).items():
            vorher = alt.get(i)
            sig = lambda x: x.model_dump_json(exclude={"pruefung", "gesperrt"})  # noqa: E731
            if vorher is None or sig(vorher) != sig(el):
                el.gesperrt = True
                geaendert.add(i)
        p.inhalt_speichern(neu)
        z = Pipeline(p).pruefen_bauen(geaendert)
        # Vom Nutzer geänderte Elemente bleiben gesperrt, auch wenn sie nicht „ok“ sind
        doc = p.inhalt()
        for i, el in elemente(doc).items():
            if i in geaendert:
                el.gesperrt = True
        p.inhalt_speichern(doc)
        return {"geaendert": sorted(geaendert), **z}

    return await asyncio.to_thread(speichern)


@app.delete("/api/projekte/{slug}/elemente/{id_}")
def element_loeschen(slug: str, id_: str):
    p = projekt(slug)
    if JOBS.laufend(slug):
        raise HTTPException(409, "Auftrag läuft noch")
    doc = p.inhalt()
    try:
        loeschen(doc, id_)
    except KeyError:
        raise HTTPException(404, "Element nicht gefunden")
    p.inhalt_speichern(doc)
    Pipeline(p).bauen(doc)
    return {"ok": True}


@app.get("/api/projekte/{slug}/elemente/{id_}")
def element(slug: str, id_: str):
    p = projekt(slug)
    try:
        art, el, _, _ = finden(p.inhalt(), id_)
    except KeyError:
        raise HTTPException(404)
    return {"art": art, "element": json.loads(el.model_dump_json())}


# ---------------------------------------------------------------- Seite / Export

@app.get("/api/projekte/{slug}/seite")
def seite(slug: str):
    p = projekt(slug)
    if not p.ausgabe.exists():
        return HTMLResponse("<p style='font:16px system-ui;padding:20px'>Noch keine Seite gebaut.</p>")
    return HTMLResponse(p.ausgabe.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})


@app.get("/api/projekte/{slug}/download")
def download(slug: str):
    p = projekt(slug)
    if not p.ausgabe.exists():
        raise HTTPException(404, "Noch keine Seite gebaut")
    return FileResponse(p.ausgabe, filename=f"{p.slug}.html", media_type="text/html")


def _pages_aktiv():
    if not laden()["pages"].get("aktiv"):
        raise HTTPException(404, "GitHub-Pages-Export ist in dieser Version nicht aktiv ([pages] aktiv = true)")


@app.get("/api/projekte/{slug}/pages")
def pages_info(slug: str):
    _pages_aktiv()
    p = projekt(slug)
    try:
        return {"ok": True, **export.vorschau(p), "status": p.meta().pages.model_dump()}
    except export.ExportFehler as e:
        return {"ok": False, "fehler": str(e), "status": p.meta().pages.model_dump()}


class PagesAuftrag(BaseModel):
    bestaetigt: bool = False


@app.post("/api/projekte/{slug}/pages")
def pages_veroeffentlichen(slug: str, auftrag: PagesAuftrag):
    _pages_aktiv()
    p = projekt(slug)
    if not auftrag.bestaetigt:
        raise HTTPException(400, "Veröffentlichen muss ausdrücklich bestätigt werden")
    try:
        return {"url": export.veroeffentlichen(p)}
    except export.ExportFehler as e:
        raise HTTPException(400, str(e))


# ---------------------------------------------------------------- Modelle / Einstellungen

@app.get("/api/faecher")
def faecher_liste():
    return faecher.liste()


@app.get("/api/einstellungen")
def einstellungen():
    cfg = laden()
    return {"config": {k: v for k, v in cfg.items()}, "pfad": str(config_pfad())}


class StandardModell(BaseModel):
    standard: str


@app.get("/api/ki")
def ki_status():
    """Für den Schalter in der Kopfzeile: Standard-Modell und ob ein Gemini-Schlüssel da ist."""
    from .modelle.gemini import schluessel
    cfg = laden()
    return {"standard": cfg["modell"]["standard"], "auswahl": list(cfg["modell"].get("auswahl") or [cfg["modell"]["standard"]]),
            "gemini_schluessel": bool(schluessel()), "pages": bool(cfg["pages"].get("aktiv")),
            "funktionen": dict(cfg["funktionen"]), "module": funktionen.aktive(cfg)}


KI_NAMEN = {"claude_code": "Claude", "gemini": "Gemini", "ollama": "Lokal"}


@app.put("/api/ki")
def ki_setzen(daten: StandardModell):
    """Standard-Modell für neue Projekte in config.toml schreiben (nur die Zeile im Abschnitt [modell])."""
    if daten.standard not in KI_NAMEN:
        raise HTTPException(400, f"unbekanntes Modell {daten.standard!r}")
    if funktionen.ki_bereit(daten.standard) is False:  # None = unbekannt (ohne Modul ki_einrichtung)
        raise HTTPException(400, f"{KI_NAMEN[daten.standard]} ist nicht eingerichtet")
    wert_setzen("modell", "standard", daten.standard)
    return ki_status()


@app.post("/api/modelle/{name}/test")
def modell_test(name: str):
    try:
        m = waehlen(name)
        antwort = m.text("Antworte nur mit dem Wort OK.", [])
        return {"ok": True, "antwort": antwort[:200]}
    except (ModellFehler, ValueError) as e:
        return {"ok": False, "fehler": str(e)}


@app.exception_handler(HTTPException)
async def http_fehler(request: Request, exc: HTTPException):
    return Response(json.dumps({"detail": exc.detail}, ensure_ascii=False), status_code=exc.status_code,
                    media_type="application/json")


__all__ = ["app", "Path"]
