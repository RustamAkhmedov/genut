"""Kommandozeile.

python -m genut serve                     Web-UI auf 127.0.0.1:8765
python -m genut render <ordner> [ziel]    inhalt.json in <ordner> prüfen und rendern (ohne KI)
python -m genut run <slug>                ganze Pipeline für ein Projekt im Terminal (ohne Kontrolle)
python -m genut neu <name> <fotos…>       Projekt anlegen und Fotos hinzufügen
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _render(args):
    from .pruefer import elemente, pruefe
    from .render.renderer import rendern
    from .schema import Dokument

    ordner = Path(args.ordner)
    doc = Dokument.model_validate_json((ordner / "inhalt.json").read_text(encoding="utf-8"))
    ergebnis = pruefe(doc, set(elemente(doc)), ordner / "fotos")
    zaehl: dict[str, int] = {}
    for i, p in ergebnis.items():
        zaehl[p.status] = zaehl.get(p.status, 0) + 1
        if p.status in ("fehler", "nicht_pruefbar"):
            print(f"  {p.status:15} {i}: {' | '.join(p.meldungen)[:160]}")
    print("Prüfung:", zaehl)
    ziel = Path(args.ziel) if args.ziel else ordner / "out" / "index.html"
    info = rendern(doc, ordner / "fotos", ordner.name, ziel, ordner / "diagramme")
    print(info["log"], "→", ziel)


def _run(args):
    from .pipeline import Pipeline
    from .projekt import Projekt

    p = Projekt.laden(args.slug)
    pl = Pipeline(p, log=lambda t, **k: print(f"[{t}]", k.get("text", ""), flush=True))
    pl.transkribieren(alle=False)
    for f in p.meta().fotos:
        if f.status == "transkribiert":
            pl.foto_status(f.datei, "kontrolliert")
    pl.generieren()


def _neu(args):
    from .pipeline import fotos_hinzufuegen
    from .projekt import Projekt

    p = Projekt.anlegen(args.name)
    fotos_hinzufuegen(p, [(Path(f).name, Path(f).read_bytes()) for f in args.fotos])
    print(p.slug)


def _serve(args):
    import uvicorn

    from .config import laden

    cfg = laden()["server"]
    if cfg["host"] not in ("127.0.0.1", "localhost", "::1"):
        sys.exit("server.host muss lokal sein (127.0.0.1)")
    uvicorn.run("genut.server:app", host=cfg["host"], port=int(cfg["port"]), log_level="info")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="genut")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.set_defaults(fn=_serve)
    r = sub.add_parser("render")
    r.add_argument("ordner")
    r.add_argument("ziel", nargs="?")
    r.set_defaults(fn=_render)
    u = sub.add_parser("run")
    u.add_argument("slug")
    u.set_defaults(fn=_run)
    n = sub.add_parser("neu")
    n.add_argument("name")
    n.add_argument("fotos", nargs="+")
    n.set_defaults(fn=_neu)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
