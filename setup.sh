#!/usr/bin/env bash
# gen_Ut – Einrichtung für macOS und Linux
#
#   ./setup.sh                      fragt nach der Version und vor jeder Installation
#   ./setup.sh --version gemini     Version vorgeben: claude | gemini | lokal
#   ./setup.sh --ja                 alle Rückfragen mit „ja“ beantworten
#
# Installiert nichts systemweit ohne Rückfrage. Python und Node.js landen bei Bedarf
# im Projektordner bzw. im Benutzerordner (keine Admin-Rechte nötig).
set -euo pipefail
cd "$(dirname "$0")"
WURZEL="$PWD"

VERSION=""
JA=0
while [ $# -gt 0 ]; do
  case "$1" in
    --version) VERSION="${2:-}"; shift 2 ;;
    --version=*) VERSION="${1#*=}"; shift ;;
    -y|--ja|--yes) JA=1; shift ;;
    -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unbekannte Option: $1 (Hilfe: ./setup.sh --help)"; exit 1 ;;
  esac
done

# ---------------------------------------------------------------- Ausgabe
if [ -t 1 ]; then B=$'\033[1m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; C=$'\033[36m'; N=$'\033[0m'; else B=""; G=""; Y=""; R=""; C=""; N=""; fi
titel()  { printf '\n%s== %s ==%s\n' "$B" "$*" "$N"; }
info()   { printf '%s▸%s %s\n' "$C" "$N" "$*"; }
ok()     { printf '%s✓%s %s\n' "$G" "$N" "$*"; }
warn()   { printf '%s!%s %s\n' "$Y" "$N" "$*"; }
abbruch(){ printf '%s✗ %s%s\n' "$R" "$*" "$N" >&2; exit 1; }

INTERAKTIV=0
if [ "$JA" = 0 ] && [ -r /dev/tty ] && { : < /dev/tty; } 2>/dev/null; then INTERAKTIV=1; fi

frage() {  # frage "Text" → 0 = ja
  [ "$JA" = 1 ] && return 0
  [ "$INTERAKTIV" = 0 ] && return 1
  local a; read -r -p "$1 [J/n] " a < /dev/tty || a=""
  case "$a" in [nN]*) return 1 ;; *) return 0 ;; esac
}

laden() {  # laden URL → stdout
  if command -v curl >/dev/null 2>&1; then curl -fsSL "$1"
  elif command -v wget >/dev/null 2>&1; then wget -qO- "$1"
  else abbruch "Weder curl noch wget gefunden – bitte eines davon installieren."; fi
}

OS="$(uname -s)"
case "$OS" in Darwin) OSNAME="macOS" ;; Linux) OSNAME="Linux" ;; *) abbruch "Dieses Skript ist für macOS und Linux. Unter Windows: setup.bat" ;; esac
case "$(uname -m)" in x86_64|amd64) ARCH="x64" ;; arm64|aarch64) ARCH="arm64" ;; *) ARCH="" ;; esac

printf '%sgen_Ut – Einrichtung (%s)%s\n' "$B" "$OSNAME" "$N"

# ---------------------------------------------------------------- Version
std_aus_config() { sed -n 's/^standard *= *"\([a-z_]*\)".*/\1/p' config.toml 2>/dev/null | head -n 1; }
if [ -z "$VERSION" ] && [ -f config.toml ]; then
  case "$(std_aus_config)" in claude_code) VERSION=claude ;; gemini) VERSION=gemini ;; ollama) VERSION=lokal ;; esac
  [ -n "$VERSION" ] && info "Version aus config.toml: $VERSION"
fi
if [ -z "$VERSION" ]; then
  if [ "$INTERAKTIV" = 1 ]; then
    echo
    echo "Welche Version willst du einrichten?"
    echo "  1) Claude  – braucht ein Claude-Abo (Pro oder höher), beste Qualität"
    echo "  2) Gemini  – gratis mit Google-Schlüssel (empfohlen, wenn du kein Claude-Abo hast)"
    echo "  3) Lokal   – Ollama auf deinem Computer, nichts geht ins Internet (experimentell)"
    read -r -p "Auswahl [2]: " w < /dev/tty || w=""
    case "${w:-2}" in 1) VERSION=claude ;; 3) VERSION=lokal ;; *) VERSION=gemini ;; esac
  else
    abbruch "Bitte die Version angeben: ./setup.sh --version claude|gemini|lokal"
  fi
fi
case "$VERSION" in claude|gemini|lokal) ;; *) abbruch "Unbekannte Version '$VERSION' (claude, gemini oder lokal)" ;; esac
[ -f "versionen/$VERSION.toml" ] || abbruch "versionen/$VERSION.toml fehlt – ist das der gen_Ut-Ordner?"

# ---------------------------------------------------------------- Python
titel "Python"
PY_OK='import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'
venv_ok() { [ -x .venv/bin/python ] && .venv/bin/python -c "$PY_OK" 2>/dev/null; }

uv_finden() {
  if command -v uv >/dev/null 2>&1; then command -v uv; return; fi
  for k in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do [ -x "$k" ] && { echo "$k"; return; }; done
  return 1
}

if venv_ok; then
  ok "Python-Umgebung .venv ist schon da ($(.venv/bin/python --version))"
else
  rm -rf .venv
  PY=""
  for k in python3 python3.14 python3.13 python3.12 python3.11; do
    if command -v "$k" >/dev/null 2>&1 && "$k" -c "$PY_OK" 2>/dev/null; then PY="$(command -v "$k")"; break; fi
  done
  if [ -n "$PY" ] && "$PY" -m venv .venv >/dev/null 2>&1 && venv_ok; then
    ok "Python-Umgebung mit $("$PY" --version) angelegt"
  else
    rm -rf .venv
    if [ -n "$PY" ]; then warn "$PY kann keine Umgebung anlegen (unter Debian/Ubuntu fehlt oft python3-venv)."
    else warn "Kein Python 3.11 oder neuer gefunden."; fi
    UV="$(uv_finden || true)"
    if [ -z "$UV" ]; then
      frage "Python über „uv“ in deinen Benutzerordner installieren (ohne Admin-Rechte, ca. 50 MB)?" \
        || abbruch "Ohne Python geht es nicht. Installiere Python 3.11+ von https://www.python.org und starte das Setup neu."
      laden https://astral.sh/uv/install.sh | sh >/dev/null
      UV="$(uv_finden)" || abbruch "uv konnte nicht installiert werden."
    fi
    info "Lade Python 3.12 und lege .venv an …"
    "$UV" venv --python 3.12 .venv >/dev/null 2>&1 || abbruch "uv konnte keine Python-Umgebung anlegen."
    "$UV" pip install --python .venv/bin/python pip >/dev/null 2>&1 || true
    venv_ok || abbruch "Die Python-Umgebung funktioniert nicht."
    ok "Python-Umgebung mit $(.venv/bin/python --version) angelegt"
  fi
fi

info "Installiere die Python-Pakete (beim ersten Mal ein paar Minuten) …"
mkdir -p .werkzeuge
if .venv/bin/python -m pip --version >/dev/null 2>&1; then
  .venv/bin/python -m pip install --disable-pip-version-check -e . > .werkzeuge/pip.log 2>&1 \
    || { tail -n 25 .werkzeuge/pip.log; abbruch "pip install ist fehlgeschlagen (ganzes Protokoll: .werkzeuge/pip.log)."; }
else
  "$(uv_finden)" pip install --python .venv/bin/python -e . > .werkzeuge/pip.log 2>&1 \
    || { tail -n 25 .werkzeuge/pip.log; abbruch "Paketinstallation ist fehlgeschlagen (Protokoll: .werkzeuge/pip.log)."; }
fi
ok "Python-Pakete installiert"

# ---------------------------------------------------------------- Node.js
titel "Node.js"
NODE_OK='process.exit(+process.versions.node.split(".")[0] >= 20 ? 0 : 1)'
NODE_BIN=""
if [ -x .werkzeuge/node/bin/node ] && .werkzeuge/node/bin/node --version >/dev/null 2>&1; then
  NODE_BIN="$WURZEL/.werkzeuge/node/bin"
elif command -v node >/dev/null 2>&1 && node -e "$NODE_OK" 2>/dev/null && command -v npm >/dev/null 2>&1; then
  NODE_BIN="$(dirname "$(command -v node)")"
else
  if command -v node >/dev/null 2>&1; then warn "Node.js $(node --version) ist zu alt (mindestens 20)."; else warn "Node.js fehlt."; fi
  [ -n "$ARCH" ] || abbruch "Unbekannte Prozessorarchitektur – bitte Node.js 20+ von https://nodejs.org installieren."
  frage "Node.js (LTS) in den gen_Ut-Ordner herunterladen (ohne Admin-Rechte, ca. 50 MB)?" \
    || abbruch "Ohne Node.js geht es nicht. Installiere es von https://nodejs.org und starte das Setup neu."
  # neueste LTS je Hauptversion (ab 20), neueste zuerst – falls eine auf diesem System nicht startet
  # (z. B. fehlende libatomic), wird die nächstältere probiert
  LTS="$(laden https://nodejs.org/dist/index.json | .venv/bin/python -c '
import json, sys
gesehen = {}
for r in json.load(sys.stdin):
    major = int(r["version"].lstrip("v").split(".")[0])
    if r["lts"] and major >= 20 and major not in gesehen:
        gesehen[major] = r["version"]
print(" ".join(gesehen[m] for m in sorted(gesehen, reverse=True)))')"
  [ "$OS" = Darwin ] && NOS=darwin || NOS=linux
  mkdir -p .werkzeuge
  for NV in $LTS; do
    info "Lade Node.js $NV …"
    rm -rf .werkzeuge/node ".werkzeuge/node-$NV-$NOS-$ARCH"
    laden "https://nodejs.org/dist/$NV/node-$NV-$NOS-$ARCH.tar.gz" | tar -xz -C .werkzeuge || continue
    mv ".werkzeuge/node-$NV-$NOS-$ARCH" .werkzeuge/node
    if .werkzeuge/node/bin/node --version >/dev/null 2>&1; then NODE_BIN="$WURZEL/.werkzeuge/node/bin"; break; fi
    warn "Node.js $NV startet auf diesem System nicht – probiere eine ältere Version."
    rm -rf .werkzeuge/node
  done
  [ -n "$NODE_BIN" ] || abbruch "Keine Node.js-Version läuft hier. Bitte Node.js 20+ über die Paketverwaltung installieren (z. B. sudo apt install nodejs npm)."
fi
ok "Node.js $("$NODE_BIN/node" --version)"
info "Installiere die Node-Pakete (MathJax, Mermaid, sql.js) …"
PATH="$NODE_BIN:$PATH" npm ci --no-audit --no-fund --loglevel=error > .werkzeuge/npm.log 2>&1 \
  || { tail -n 25 .werkzeuge/npm.log; abbruch "npm ci ist fehlgeschlagen (Protokoll: .werkzeuge/npm.log)."; }
ok "Node-Pakete installiert"

# ---------------------------------------------------------------- config.toml
titel "Konfiguration"
if [ ! -f config.toml ]; then
  cp "versionen/$VERSION.toml" config.toml
  ok "config.toml für die Version „$VERSION“ angelegt"
else
  SOLL="$(sed -n 's/^standard *= *"\([a-z_]*\)".*/\1/p' "versionen/$VERSION.toml" | head -n 1)"
  if [ "$(std_aus_config)" != "$SOLL" ]; then
    if frage "config.toml ist für eine andere Version eingestellt. Auf „$VERSION“ umstellen (alte Datei → config.toml.bak)?"; then
      cp config.toml config.toml.bak && cp "versionen/$VERSION.toml" config.toml && ok "config.toml umgestellt"
    else warn "config.toml bleibt unverändert"; fi
  else
    ok "config.toml passt schon"
  fi
fi

# ---------------------------------------------------------------- KI einrichten
case "$VERSION" in
claude)
  titel "Claude"
  CL="$(command -v claude 2>/dev/null || true)"
  [ -z "$CL" ] && [ -x "$HOME/.local/bin/claude" ] && CL="$HOME/.local/bin/claude"
  if [ -z "$CL" ]; then
    if frage "Die Claude-Code-CLI fehlt. Jetzt installieren (offizieller Installer von claude.ai)?"; then
      laden https://claude.ai/install.sh | bash || warn "Installation fehlgeschlagen."
      CL="$(command -v claude 2>/dev/null || true)"; [ -z "$CL" ] && [ -x "$HOME/.local/bin/claude" ] && CL="$HOME/.local/bin/claude"
    fi
  fi
  if [ -n "$CL" ]; then
    ok "Claude Code gefunden: $CL"
    if ! command -v claude >/dev/null 2>&1; then
      # nicht im PATH → vollen Pfad in config.toml eintragen
      CL="$CL" .venv/bin/python -c 'import os, re, pathlib; p = pathlib.Path("config.toml"); p.write_text(re.sub(r"(?m)^befehl = \"claude\"", "befehl = \"" + os.environ["CL"] + "\"", p.read_text()))'
    fi
    warn "Melde dich einmal mit deinem Claude-Konto an (Pro oder höher): im Terminal „$CL“ starten, Anmeldung durchführen, mit /exit beenden."
    if [ "$INTERAKTIV" = 1 ] && frage "Claude jetzt zum Anmelden starten?"; then "$CL" < /dev/tty || true; fi
  else
    warn "Ohne Claude Code funktioniert diese Version nicht. Anleitung: https://claude.com/claude-code"
  fi
  ;;
gemini)
  titel "Gemini"
  if grep -qE '^\s*(export\s+)?GEMINI_API_KEY\s*=\s*\S' .env 2>/dev/null; then
    ok "Gemini-Schlüssel steht schon in .env"
  else
    KEY="${GEMINI_API_KEY:-}"
    if [ -z "$KEY" ] && [ "$INTERAKTIV" = 1 ]; then
      echo "Du brauchst einen kostenlosen Schlüssel von Google AI Studio:"
      echo "  1. https://aistudio.google.com/apikey öffnen und mit einem Google-Konto anmelden"
      echo "  2. „Create API key“ klicken und den Schlüssel kopieren"
      if frage "Seite jetzt im Browser öffnen?"; then
        (open https://aistudio.google.com/apikey || xdg-open https://aistudio.google.com/apikey) >/dev/null 2>&1 || true
      fi
      read -r -s -p "Schlüssel einfügen (wird nicht angezeigt): " KEY < /dev/tty || KEY=""; echo
    fi
    KEY="$(printf '%s' "$KEY" | tr -d '[:space:]')"
    if [ -n "$KEY" ]; then
      printf 'GEMINI_API_KEY=%s\n' "$KEY" >> .env && chmod 600 .env
      ok "Schlüssel in .env gespeichert (nur auf diesem Computer)"
    else
      warn "Kein Schlüssel eingegeben. Später nachtragen: Datei .env mit der Zeile GEMINI_API_KEY=… anlegen."
    fi
  fi
  schluessel_ok() { .venv/bin/python -c 'from genut.modelle.gemini import Gemini; Gemini({"modell": ""})._kandidaten()' >/dev/null 2>&1; }
  if grep -q GEMINI_API_KEY .env 2>/dev/null; then
    if schluessel_ok; then
      ok "Schlüssel funktioniert"
    else
      warn "Schlüssel wurde nicht akzeptiert (oder keine Internetverbindung)."
      if [ "$INTERAKTIV" = 1 ] && frage "Schlüssel neu eingeben?"; then
        read -r -s -p "Schlüssel einfügen (wird nicht angezeigt): " KEY < /dev/tty || KEY=""; echo
        KEY="$(printf '%s' "$KEY" | tr -d '[:space:]')"
        if [ -n "$KEY" ]; then
          grep -v GEMINI_API_KEY .env > .env.neu || true
          printf 'GEMINI_API_KEY=%s\n' "$KEY" >> .env.neu && mv .env.neu .env && chmod 600 .env
          if schluessel_ok; then ok "Schlüssel funktioniert"; else warn "Auch dieser Schlüssel geht nicht – prüfe ihn auf aistudio.google.com."; fi
        fi
      else
        warn "Prüfe die Zeile GEMINI_API_KEY=… in der Datei .env."
      fi
    fi
  fi
  ;;
lokal)
  titel "Lokal (Ollama) – experimentell"
  warn "Die lokale Version ist experimentell: langsamer und einfacher als Claude oder Gemini."
  if [ "$OS" = Darwin ]; then RAM_GB=$(( $(sysctl -n hw.memsize) / 1073741824 )); else RAM_GB=$(( $(awk '/MemTotal/ {print $2}' /proc/meminfo) / 1048576 )); fi
  [ "$RAM_GB" -lt 15 ] && warn "Dein Computer hat ${RAM_GB} GB RAM – empfohlen sind 16 GB. Es kann sehr langsam werden."
  if ! command -v ollama >/dev/null 2>&1; then
    if [ "$OS" = Darwin ]; then
      if command -v brew >/dev/null 2>&1 && frage "Ollama mit Homebrew installieren?"; then brew install ollama
      else abbruch "Bitte Ollama von https://ollama.com/download installieren und das Setup neu starten."; fi
    else
      frage "Ollama installieren (offizieller Installer, fragt nach dem Admin-Passwort)?" \
        || abbruch "Bitte Ollama von https://ollama.com/download installieren und das Setup neu starten."
      laden https://ollama.com/install.sh | sh
    fi
  fi
  command -v ollama >/dev/null 2>&1 || abbruch "Ollama wurde nicht gefunden."
  if ! ollama list >/dev/null 2>&1; then
    info "Starte Ollama …"; (nohup ollama serve >/dev/null 2>&1 &); sleep 3
  fi
  MODELL="$(.venv/bin/python -c 'from genut.config import laden; print(laden()["ollama"]["modell"])')"
  if ollama list 2>/dev/null | awk '{print $1}' | grep -qx "$MODELL"; then
    ok "Modell $MODELL ist schon da"
  elif frage "Modell $MODELL herunterladen (ca. 3 GB)?"; then
    ollama pull "$MODELL" && ok "Modell $MODELL geladen"
  else
    warn "Ohne Modell geht es nicht: später „ollama pull $MODELL“ ausführen."
  fi
  ;;
esac

# ---------------------------------------------------------------- Startbefehl
titel "Startbefehl"
{
  echo '#!/usr/bin/env bash'
  echo '# gen_Ut starten (angelegt von setup.sh). Beenden mit Strg+C.'
  echo 'cd "$(dirname "$0")"'
  if [ "$VERSION" = lokal ]; then
    echo 'if command -v ollama >/dev/null 2>&1 && ! ollama list >/dev/null 2>&1; then (nohup ollama serve >/dev/null 2>&1 &); sleep 3; fi'
  fi
  echo 'PORT="$(.venv/bin/python -c '"'"'from genut.config import laden; print(laden()["server"]["port"])'"'"')"'
  echo 'URL="http://127.0.0.1:$PORT"'
  echo '( sleep 3; if [ "$(uname -s)" = Darwin ]; then open "$URL"; elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"; fi ) >/dev/null 2>&1 &'
  echo 'echo "gen_Ut läuft auf $URL – Fenster offen lassen, beenden mit Strg+C"'
  echo 'exec .venv/bin/python -m genut serve'
} > start.sh
chmod +x start.sh
if [ "$OS" = Darwin ]; then cp start.sh start.command && chmod +x start.command; fi
ok "start.sh angelegt$([ "$OS" = Darwin ] && echo ' (und start.command zum Doppelklicken im Finder)')"

printf '\n%sFertig!%s gen_Ut ist eingerichtet (Version: %s).\n' "$G$B" "$N" "$VERSION"
echo "Starten:  ./start.sh   – dann öffnet sich http://127.0.0.1:8765 im Browser."
