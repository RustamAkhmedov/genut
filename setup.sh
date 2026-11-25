#!/usr/bin/env bash
# gen_Ut – Einrichtung für macOS und Linux
#
# Installiert nichts systemweit ohne Rückfrage. Python und Node.js landen bei Bedarf im Projektordner
# bzw. im Benutzerordner (keine Admin-Rechte nötig). Danach fragt das Setup der Reihe nach Claude, Gemini
# und ein lokales Modell ab (jeweils überspringbar) und zum Schluss die Standard-KI für neue Projekte.
# Was sich in Python prüfen lässt (Zustand, Modellvorschläge, Schlüssel), fragt es über
# `python -m genut ki …` ab (specs/005b-ein-genut/contracts/cli.md).
set -euo pipefail
cd "$(dirname "$0")"
WURZEL="$PWD"
export PYTHONUTF8=1

hilfe() {
  cat <<'EOF'
gen_Ut – Einrichtung für macOS und Linux

  ./setup.sh                              alles einrichten, fragt nach Claude, Gemini und Lokal
  ./setup.sh --nur claude|gemini|lokal    nur diesen Teil nachholen
  ./setup.sh --standard claude|gemini|lokal
                                          Standard-KI für neue Projekte vorgeben
  ./setup.sh --lokal-modell gemma3:4b     lokales Modell ohne Rückfrage laden
  ./setup.sh --ja                         Rückfragen zu Python und Node.js mit „ja“ beantworten
                                          (installiert Claude oder Ollama nur zusammen mit
                                          --nur claude, --nur lokal oder --lokal-modell)
  ./setup.sh --version claude             alt, nur Vorschlag für die Standard-KI
  ./setup.sh --hilfe                      diese Hilfe

Ohne Terminal (z. B. in Tests) fragt das Setup nichts und richtet nur ein, was vorgegeben ist:
GEMINI_API_KEY=… als Umgebungsvariable, --lokal-modell, --standard.
EOF
}

# ---------------------------------------------------------------- Ausgabe
if [ -t 1 ]; then B=$'\033[1m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; C=$'\033[36m'; N=$'\033[0m'; else B=""; G=""; Y=""; R=""; C=""; N=""; fi
titel()  { printf '\n%s== %s ==%s\n' "$B" "$*" "$N"; }
info()   { printf '%s▸%s %s\n' "$C" "$N" "$*"; }
ok()     { printf '%s✓%s %s\n' "$G" "$N" "$*"; }
warn()   { printf '%s!%s %s\n' "$Y" "$N" "$*"; }
abbruch(){ printf '%s✗ %s%s\n' "$R" "$*" "$N" >&2; exit 1; }

# ---------------------------------------------------------------- Schalter
NUR=""; STANDARD=""; LOKAL_MODELL=""; ALT_VERSION=""; ALT_VORSCHLAG=""; JA=0
wert() { [ $# -ge 2 ] && [ -n "$2" ] || abbruch "$1 braucht einen Wert (Hilfe: ./setup.sh --hilfe)"; }
while [ $# -gt 0 ]; do
  case "$1" in
    --nur) wert "$@"; NUR="$2"; shift 2 ;;
    --nur=*) NUR="${1#*=}"; shift ;;
    --standard) wert "$@"; STANDARD="$2"; shift 2 ;;
    --standard=*) STANDARD="${1#*=}"; shift ;;
    --lokal-modell) wert "$@"; LOKAL_MODELL="$2"; shift 2 ;;
    --lokal-modell=*) LOKAL_MODELL="${1#*=}"; shift ;;
    --version) wert "$@"; ALT_VERSION="$2"; shift 2 ;;
    --version=*) ALT_VERSION="${1#*=}"; shift ;;
    -y|--ja|--yes) JA=1; shift ;;
    -h|--help|--hilfe) hilfe; exit 0 ;;
    *) abbruch "Unbekannte Option: $1 (Hilfe: ./setup.sh --hilfe)" ;;
  esac
done

# claude | gemini | lokal (auch die internen Namen) → Name in config.toml
ki_name() { case "$1" in claude|claude_code) echo claude_code ;; gemini) echo gemini ;; lokal|ollama) echo ollama ;; *) echo "" ;; esac; }
ki_titel() { case "$1" in claude_code) echo Claude ;; gemini) echo Gemini ;; ollama) echo "Lokal" ;; *) echo "$1" ;; esac; }

case "$NUR" in ""|claude|gemini|lokal) ;; *) abbruch "--nur kennt claude, gemini und lokal (nicht „${NUR}“)" ;; esac
if [ -n "$STANDARD" ]; then
  [ -n "$(ki_name "$STANDARD")" ] || abbruch "--standard kennt claude, gemini und lokal (nicht „${STANDARD}“)"
  STANDARD="$(ki_name "$STANDARD")"
fi
case "$LOKAL_MODELL" in *[!A-Za-z0-9._:/-]*) abbruch "Ungültiger Modellname „${LOKAL_MODELL}“" ;; esac
if [ -n "$ALT_VERSION" ]; then
  if [ -z "$(ki_name "$ALT_VERSION")" ]; then
    warn "--version gibt es nicht mehr, es gibt nur noch ein gen_Ut mit allen KIs. „${ALT_VERSION}“ wird ignoriert."
  elif [ -n "$STANDARD" ]; then
    warn "--version ist veraltet und wird neben --standard ignoriert."
  else
    ALT_VORSCHLAG="$(ki_name "$ALT_VERSION")"
    warn "--version ist veraltet: „${ALT_VERSION}“ gilt nur noch als Vorschlag für die Standard-KI (alle KIs werden abgefragt)."
  fi
fi

# Interaktiv nur mit Terminal (stdin und /dev/tty); --ja beantwortet nur die Rückfragen zur Umgebung.
INTERAKTIV=0
if [ "$JA" = 0 ] && [ -t 0 ] && [ -r /dev/tty ] && { : < /dev/tty; } 2>/dev/null; then INTERAKTIV=1; fi

frage() {  # frage "Text" [j|n] → 0 = ja; j/n ist die Antwort bei Enter
  local vorgabe="${2:-j}" a=""
  if [ "$JA" = 1 ]; then return 0; fi
  if [ "$INTERAKTIV" = 0 ]; then return 1; fi
  if [ "$vorgabe" = j ]; then read -r -p "$1 [J/n] " a < /dev/tty || a=""
  else read -r -p "$1 [j/N] " a < /dev/tty || a=""; fi
  case "$a" in [jJyY]*) return 0 ;; [nN]*) return 1 ;; esac
  [ "$vorgabe" = j ]
}

# Teil ausdrücklich verlangt (--nur …, für Lokal auch --lokal-modell)?
explizit() {
  if [ "$NUR" = "$1" ]; then return 0; fi
  if [ "$1" = lokal ] && [ -n "$LOKAL_MODELL" ]; then return 0; fi
  return 1
}

# Installation von Claude oder Ollama: interaktiv nach Rückfrage, ohne Terminal nur mit --ja und ausdrücklichem Teil
installieren_erlaubt() {  # installieren_erlaubt "Frage" teil [j|n]
  if [ "$INTERAKTIV" = 1 ]; then frage "$1" "${3:-j}"; return; fi
  if [ "$JA" = 1 ] && explizit "$2"; then info "$1 – ja (--ja)"; return 0; fi
  return 1
}

laden() {  # laden URL → stdout
  if command -v curl >/dev/null 2>&1; then curl -fsSL "$1"
  elif command -v wget >/dev/null 2>&1; then wget -qO- "$1"
  else abbruch "Weder curl noch wget gefunden – bitte eines davon installieren."; fi
}

browser_oeffnen() {
  if [ "$OS" = Darwin ]; then open "$1" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$1" >/dev/null 2>&1 || true; fi
}

OS="$(uname -s)"
case "$OS" in Darwin) OSNAME="macOS" ;; Linux) OSNAME="Linux" ;; *) abbruch "Dieses Skript ist für macOS und Linux. Unter Windows: setup.bat" ;; esac
case "$(uname -m)" in x86_64|amd64) ARCH="x64" ;; arm64|aarch64) ARCH="arm64" ;; *) ARCH="" ;; esac

printf '%sgen_Ut – Einrichtung (%s)%s\n' "$B" "$OSNAME" "$N"

# ---------------------------------------------------------------- Version (versionen/AKTIV)
AKTIV=""
if [ -f versionen/AKTIV ]; then AKTIV="$(head -n 1 versionen/AKTIV | tr -d '[:space:]')"; fi
if [ "$AKTIV" = schule ]; then
  info "Die Schul-Version läuft als Docker-Image auf einem Server, den ein Admin betreibt."
  info "Dieses Setup richtet sie nicht ein. Anleitung: docs/schule/"
  exit 0
fi

# ---------------------------------------------------------------- Python
titel "Python"
PY_OK='import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'
PYBIN="$WURZEL/.venv/bin/python"
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

mkdir -p .werkzeuge
if [ -n "$NUR" ] && .venv/bin/python -c 'import genut' >/dev/null 2>&1; then
  ok "Python-Pakete sind schon installiert"
else
  info "Installiere die Python-Pakete (beim ersten Mal ein paar Minuten) …"
  if .venv/bin/python -m pip --version >/dev/null 2>&1; then
    .venv/bin/python -m pip install --disable-pip-version-check -e . > .werkzeuge/pip.log 2>&1 \
      || { tail -n 25 .werkzeuge/pip.log; abbruch "pip install ist fehlgeschlagen (ganzes Protokoll: .werkzeuge/pip.log)."; }
  else
    "$(uv_finden)" pip install --python .venv/bin/python -e . > .werkzeuge/pip.log 2>&1 \
      || { tail -n 25 .werkzeuge/pip.log; abbruch "Paketinstallation ist fehlgeschlagen (Protokoll: .werkzeuge/pip.log)."; }
  fi
  ok "Python-Pakete installiert"
fi

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
if [ -n "$NUR" ] && [ -d node_modules ]; then
  ok "Node-Pakete sind schon installiert"
else
  info "Installiere die Node-Pakete (MathJax, Mermaid, sql.js, PDFKit) …"
  PATH="$NODE_BIN:$PATH" npm ci --no-audit --no-fund --loglevel=error > .werkzeuge/npm.log 2>&1 \
    || { tail -n 25 .werkzeuge/npm.log; abbruch "npm ci ist fehlgeschlagen (Protokoll: .werkzeuge/npm.log)."; }
  ok "Node-Pakete installiert"
fi

# ---------------------------------------------------------------- Hilfen für die KI-Schritte
ki() { "$PYBIN" -m genut ki "$@"; }
KI_DA=0
if "$PYBIN" -m genut ki --help >/dev/null 2>&1; then KI_DA=1; fi
US=$'\037'  # Trenner für Felder (auch leere Felder bleiben erhalten)

std_aus_config() { sed -n 's/^standard *= *"\([a-z_]*\)".*/\1/p' config.toml 2>/dev/null | head -n 1; }

# ki_zustand NAME → ZU (bereit|nicht_eingerichtet|problem), UR (Ursache), AK (Aktion), BE (voller Pfad, nur Claude)
ki_zustand() {
  local roh=""
  roh="$(ki zustand --json "$1" 2>/dev/null)" || true
  IFS="$US" read -r ZU UR AK BE <<EOF || true
$(printf '%s' "$roh" | "$PYBIN" -c 'import json, sys
try:
    d = json.load(sys.stdin)
except ValueError:
    d = {}
print("\037".join(str(d.get(k) or "") for k in ("zustand", "ursache", "aktion", "befehl")))' 2>/dev/null)
EOF
  if [ -z "$ZU" ]; then ZU=problem; UR="Prüfung fehlgeschlagen"; AK=""; BE=""; fi
}

# alle_zustaende → ZUSTAENDE (Zeilen name␟zustand␟ursache in der Reihenfolge von auswahl), BEREIT (Namen)
alle_zustaende() {
  local roh="" n z u
  roh="$(ki zustand --json 2>/dev/null)" || true
  ZUSTAENDE="$(printf '%s' "$roh" | "$PYBIN" -c 'import json, sys
try:
    d = json.load(sys.stdin)
except ValueError:
    d = {}
for z in d.get("zustaende") or []:
    print("\037".join(str(z.get(k) or "") for k in ("name", "zustand", "ursache")))' 2>/dev/null)" || true
  BEREIT=""
  while IFS="$US" read -r n z u; do
    if [ "$z" = bereit ]; then BEREIT="$BEREIT $n"; fi
  done <<EOF
$ZUSTAENDE
EOF
  BEREIT="${BEREIT# }"
}

ist_bereit() { case " $BEREIT " in *" $1 "*) return 0 ;; esac; return 1; }

# ---------------------------------------------------------------- config.toml
titel "Konfiguration"
VORLAGE=genut
case "$AKTIV" in
  ""|genut) ;;
  claude|gemini|lokal) info "versionen/AKTIV nennt die alte Version „${AKTIV}“ – es gibt nur noch genut mit allen KIs." ;;
  *) if [ -f "versionen/$AKTIV.toml" ]; then VORLAGE="$AKTIV"; else warn "versionen/$AKTIV.toml fehlt – nehme versionen/genut.toml."; fi ;;
esac
CONFIG_NEU=0
if [ ! -f config.toml ]; then
  [ -f "versionen/$VORLAGE.toml" ] || abbruch "versionen/$VORLAGE.toml fehlt (ist das der gen_Ut-Ordner?)"
  cp "versionen/$VORLAGE.toml" config.toml
  CONFIG_NEU=1
  ok "config.toml angelegt (Vorlage: versionen/$VORLAGE.toml)"
elif [ "$KI_DA" = 1 ]; then
  # vorhandene Datei: nur fehlende KIs in [modell] auswahl ergänzen (vorher config.toml.bak), sonst nichts ändern
  if MELDUNG="$(ki auswahl-ergaenzen 2>&1)"; then
    case "$MELDUNG" in *ergänzt:*) ok "$MELDUNG (Sicherung: config.toml.bak)" ;; *) ok "config.toml ist schon da ($MELDUNG)" ;; esac
  else
    warn "config.toml ließ sich nicht ergänzen: $MELDUNG"
  fi
else
  ok "config.toml ist schon da"
fi

# ---------------------------------------------------------------- Claude
claude_pfad_eintragen() {  # liegt die CLI nicht im Suchpfad, kommt ihr voller Pfad in config.toml
  if [ -n "$BE" ] && ! command -v claude >/dev/null 2>&1; then
    if ki setzen claude_code.befehl "$BE" >/dev/null; then info "Voller Pfad in config.toml eingetragen: $BE"; fi
  fi
}

claude_anmelden() {
  local cl="${BE:-claude}"
  if [ "$INTERAKTIV" = 0 ]; then
    warn "Melde dich einmal an (Claude-Abo Pro oder höher): im Terminal „${cl}“ starten, anmelden, mit /exit beenden."
    return 0
  fi
  info "Zum Anmelden startet Claude im Terminal: folge der Anmeldung (Browser), danach mit /exit beenden."
  if frage "Claude jetzt zum Anmelden starten?"; then
    "$cl" < /dev/tty > /dev/tty 2>&1 || true
    ki_zustand claude_code
    if [ "$ZU" = bereit ]; then ok "Claude ist angemeldet und bereit"; return 0; fi
  fi
  warn "Claude ist noch nicht angemeldet. Später: im Terminal „${cl}“ starten und anmelden."
}

schritt_claude() {
  titel "Claude"
  ki_zustand claude_code
  case "$ZU" in
    bereit)
      ok "Claude gefunden${BE:+: $BE}"
      claude_pfad_eintragen ;;
    problem)
      claude_pfad_eintragen
      if [ "$AK" = anmelden ]; then
        warn "Claude ist installiert, aber nicht angemeldet."
        claude_anmelden
      else
        warn "Claude: Problem (${UR:-unbekannt})."
      fi ;;
    *)
      if [ "$INTERAKTIV" = 1 ]; then info "Claude braucht ein Claude-Abo (Pro oder höher) und liefert die beste Qualität."; fi
      if installieren_erlaubt "Claude einrichten (offizieller Installer von claude.ai, ohne Admin-Rechte)?" claude "$(if explizit claude; then echo j; else echo n; fi)"; then
        info "Installiere Claude Code …"
        if laden https://claude.ai/install.sh | bash; then :; else warn "Die Installation meldet einen Fehler."; fi
        ki_zustand claude_code
        if [ "$ZU" = nicht_eingerichtet ]; then
          warn "Claude Code wurde nicht gefunden. Anleitung: https://claude.com/claude-code"
          return 0
        fi
        ok "Claude Code installiert${BE:+: $BE}"
        claude_pfad_eintragen
        if [ "$ZU" = bereit ]; then ok "Claude ist bereit"; else claude_anmelden; fi
      else
        info "Claude übersprungen. Später: im Tool oben auf Claude klicken oder ./setup.sh --nur claude"
      fi ;;
  esac
}

# ---------------------------------------------------------------- Gemini
gemini_pruefen() {  # Schlüssel in $1 (nie als Argument an ein Programm) → 0 gespeichert, 1 abgelehnt, 3 keine Verbindung
  local rc=0 meldung=""
  meldung="$(printf '%s' "$1" | ki gemini-pruefen 2>&1)" || rc=$?
  if [ "$rc" = 0 ]; then ok "$meldung"; else warn "$meldung"; fi
  return "$rc"
}

gemini_ungeprueft_speichern() {
  printf '%s' "$1" | "$PYBIN" -c 'import sys
from genut.funktionen.ki_einrichtung import env
env.schluessel_speichern(sys.stdin.read().strip())'
}

gemini_eingeben() {  # fragt verdeckt nach dem Schlüssel; bei „abgelehnt“ einmal neu
  local key="" rc versuch=1
  echo "Gemini ist gratis mit einem Schlüssel von Google AI Studio:"
  echo "  1. https://aistudio.google.com/apikey öffnen und mit einem Google-Konto anmelden"
  echo "  2. „Create API key“ klicken und den Schlüssel kopieren"
  if frage "Seite jetzt im Browser öffnen?"; then browser_oeffnen https://aistudio.google.com/apikey; fi
  while [ "$versuch" -le 2 ]; do
    read -r -s -p "Schlüssel einfügen (wird nicht angezeigt, Enter = überspringen): " key < /dev/tty || key=""; echo
    key="$(printf '%s' "$key" | tr -d '[:space:]')"
    if [ -z "$key" ]; then info "Gemini übersprungen. Später: im Tool oben auf Gemini klicken oder ./setup.sh --nur gemini"; return 0; fi
    rc=0; gemini_pruefen "$key" || rc=$?
    case "$rc" in
      0) unset GEMINI_API_KEY GOOGLE_API_KEY; return 0 ;;  # ab jetzt zählt .env
      3) if frage "Schlüssel trotzdem ungeprüft speichern?" n; then
           if gemini_ungeprueft_speichern "$key"; then ok "Schlüssel ungeprüft in .env gespeichert"; unset GEMINI_API_KEY GOOGLE_API_KEY; fi
         fi
         return 0 ;;
    esac
    versuch=$((versuch + 1))
    if [ "$versuch" -le 2 ]; then info "Prüfe den Schlüssel auf aistudio.google.com und füge ihn noch einmal ein."; fi
  done
  warn "Gemini übersprungen. Später: im Tool oben auf Gemini klicken oder ./setup.sh --nur gemini"
}

schritt_gemini() {
  titel "Gemini"
  local rc
  if [ -n "${GEMINI_API_KEY:-}" ]; then
    info "Prüfe den Schlüssel aus GEMINI_API_KEY …"
    rc=0; gemini_pruefen "$(printf '%s' "$GEMINI_API_KEY" | tr -d '[:space:]')" || rc=$?
    if [ "$rc" = 1 ] && [ "$INTERAKTIV" = 1 ]; then gemini_eingeben; fi
    return 0
  fi
  ki_zustand gemini
  if [ "$ZU" = bereit ]; then ok "Gemini ist bereit (Schlüssel in .env)"; return 0; fi
  if [ "$AK" != schluessel ]; then
    warn "Gemini: ${UR:-Problem}. Der gespeicherte Schlüssel bleibt; später nochmal prüfen."
    return 0
  fi
  if [ "$ZU" = problem ]; then warn "Gemini: ${UR}."; fi
  if [ "$INTERAKTIV" = 1 ]; then
    gemini_eingeben
  else
    info "Gemini übersprungen (ohne Terminal nur mit GEMINI_API_KEY=…)."
  fi
}

# ---------------------------------------------------------------- Lokal (Ollama)
OLLAMA_DIR=""
ollama_finden() {  # → 0 und PATH ergänzt, wenn ollama da ist
  local k
  if command -v ollama >/dev/null 2>&1; then OLLAMA_DIR="$(dirname "$(command -v ollama)")"; return 0; fi
  for k in /opt/homebrew/bin/ollama /usr/local/bin/ollama /Applications/Ollama.app/Contents/Resources/ollama "$HOME/.local/bin/ollama"; do
    if [ -x "$k" ]; then OLLAMA_DIR="$(dirname "$k")"; PATH="$OLLAMA_DIR:$PATH"; export PATH; return 0; fi
  done
  return 1
}
ollama_laeuft() { ollama list >/dev/null 2>&1; }
ollama_hat() { ollama list 2>/dev/null | awk 'NR > 1 {print $1}' | grep -qxF -e "$1" -e "$1:latest"; }
ollama_starten() {  # → 0, wenn Ollama läuft
  local i=0
  if ollama_laeuft; then return 0; fi
  info "Starte Ollama …"
  (nohup ollama serve >/dev/null 2>&1 &)
  while [ "$i" -lt 10 ] && ! ollama_laeuft; do sleep 1; i=$((i + 1)); done
  ollama_laeuft
}

ollama_installieren() {
  if [ "$OS" = Darwin ]; then
    if command -v brew >/dev/null 2>&1 && installieren_erlaubt "Ollama fehlt. Mit Homebrew installieren?" lokal; then
      brew install ollama || warn "brew install ollama ist fehlgeschlagen."
    else
      warn "Ollama fehlt: die App von https://ollama.com/download installieren, einmal öffnen und ./setup.sh --nur lokal neu starten."
      return 1
    fi
  else
    if installieren_erlaubt "Ollama fehlt. Installieren (offizieller Installer von ollama.com, fragt nach dem Admin-Passwort)?" lokal; then
      if laden https://ollama.com/install.sh | sh; then :; else warn "Der Ollama-Installer meldet einen Fehler."; fi
    else
      warn "Ollama fehlt: https://ollama.com/download (ohne Admin-Rechte: manuelle Installation laut https://docs.ollama.com/linux), danach ./setup.sh --nur lokal"
      return 1
    fi
  fi
  ollama_finden || { warn "Ollama wurde nach der Installation nicht gefunden."; return 1; }
  ok "Ollama installiert"
}

# Vorschläge als nummerierte Liste zeigen und eine Wahl lesen → MODELL, MODELL_PLATZ (1 = Platz knapp)
modell_waehlen() {
  local roh="" liste="" i name gb grund vor platz da vorwahl=1 w="" zeile keins
  roh="$(ki modelle --json 2>/dev/null)" || true
  liste="$(printf '%s' "$roh" | "$PYBIN" -c 'import json, sys
d = json.load(sys.stdin)
for i, v in enumerate(d["vorschlaege"], 1):
    gb = "{:g}".format(v["download_gb"]).replace(".", ",")
    werte = [str(i), v["name"], gb, v["begruendung"], "1" if v["vorgewaehlt"] else "",
             "1" if v["platz_warnung"] else "", "1" if v["vorhanden"] else ""]
    print("\037".join(werte))
print("keins_gut" if d.get("keins_gut") else "")' 2>/dev/null)" || true
  if [ -z "$liste" ]; then warn "Die Modellvorschläge ließen sich nicht ermitteln."; MODELL=""; return 0; fi
  keins="$(printf '%s\n' "$liste" | tail -n 1)"
  echo "Modelle, die Fotos verstehen (Urteil für diesen Computer):"
  while IFS="$US" read -r i name gb grund vor platz da; do
    if [ -z "$name" ]; then continue; fi
    zeile="  $i) $name ($gb GB) – $grund"
    if [ "$vor" = 1 ]; then zeile="$zeile [Vorwahl]"; vorwahl="$i"; fi
    if [ "$da" = 1 ]; then zeile="$zeile [schon geladen]"; elif [ "$platz" = 1 ]; then zeile="$zeile [Speicherplatz knapp]"; fi
    echo "$zeile"
  done <<EOF
$liste
EOF
  if [ "$keins" = keins_gut ]; then
    warn "Kein Modell läuft auf diesem Computer gut. Empfehlung: Gemini. Wählen kannst du trotzdem."
  fi
  read -r -p "Modell wählen [1-3, Enter = $vorwahl, 0 = keins]: " w < /dev/tty || w=""
  w="${w:-$vorwahl}"
  MODELL=""; MODELL_PLATZ=""
  case "$w" in
    0) return 0 ;;
    [1-9])
      while IFS="$US" read -r i name gb grund vor platz da; do
        if [ "$i" = "$w" ] && [ -n "$name" ]; then MODELL="$name"; MODELL_PLATZ="$platz"; fi
      done <<EOF
$liste
EOF
      if [ -z "$MODELL" ]; then warn "Keine gültige Nummer – kein Modell gewählt."; fi ;;
    *[!A-Za-z0-9._:/-]*) warn "Ungültiger Modellname – kein Modell gewählt." ;;
    *) MODELL="$w" ;;  # eigener Modellname
  esac
}

schritt_lokal() {
  titel "Lokal (Ollama) – experimentell"
  local jetzt=""
  ki_zustand ollama
  # installiert, aber nicht gestartet: erst starten, vielleicht ist dann alles da
  if [ "$AK" = starten ] && { [ "$INTERAKTIV" = 1 ] || explizit lokal; } && ollama_finden && ollama_starten; then
    ki_zustand ollama
  fi
  jetzt="$("$PYBIN" -c 'from genut.config import laden; print((laden().get("ollama") or {}).get("modell") or "")' 2>/dev/null || true)"
  if [ "$ZU" = bereit ] && { [ -z "$LOKAL_MODELL" ] || [ "$LOKAL_MODELL" = "$jetzt" ]; }; then
    ok "Lokal ist bereit (Modell $jetzt)"
    return 0
  fi
  if ! explizit lokal; then
    if [ "$INTERAKTIV" = 0 ]; then info "Lokal übersprungen (ohne Terminal nur mit --lokal-modell)."; return 0; fi
    info "Ein lokales Modell läuft auf deinem Computer, ohne Internet – langsamer und einfacher als Claude oder Gemini."
    if ! frage "Lokales Modell einrichten? (experimentell)" n; then
      info "Lokal übersprungen. Später: ./setup.sh --nur lokal"
      return 0
    fi
  fi
  if ! ollama_finden; then ollama_installieren || return 0; fi
  if ! ollama_starten; then warn "Ollama startet nicht. Starte es selbst (ollama serve) und dann ./setup.sh --nur lokal"; return 0; fi
  ok "Ollama läuft"
  MODELL="$LOKAL_MODELL"; MODELL_PLATZ=""
  if [ -z "$MODELL" ]; then
    if [ "$INTERAKTIV" = 0 ]; then info "Kein Modell vorgegeben (--lokal-modell) – übersprungen."; return 0; fi
    modell_waehlen
    if [ -z "$MODELL" ]; then info "Kein Modell gewählt. Später: ./setup.sh --nur lokal"; return 0; fi
  fi
  if ollama_hat "$MODELL"; then
    ok "Modell $MODELL ist schon geladen"
  else
    if [ "$MODELL_PLATZ" = 1 ] && ! frage "Der freie Speicherplatz reicht vielleicht nicht. Trotzdem laden?" n; then
      info "Nicht geladen. Später: ./setup.sh --nur lokal"
      return 0
    fi
    info "Lade $MODELL (das kann eine Weile dauern) …"
    if ! ollama pull "$MODELL"; then
      warn "Download von $MODELL fehlgeschlagen. Nochmal versuchen: ./setup.sh --nur lokal (setzt fort, wo möglich)"
      return 0
    fi
    ok "Modell $MODELL geladen"
  fi
  if ki setzen ollama.modell "$MODELL" >/dev/null; then ok "Lokales Modell in config.toml: $MODELL"; fi
}

# ---------------------------------------------------------------- Standard-KI
standard_setzen() {
  if [ "$1" != "$(std_aus_config)" ]; then ki setzen modell.standard "$1" >/dev/null || { warn "Standard-KI ließ sich nicht setzen."; return 0; }; fi
  ok "Standard-KI für neue Projekte: $(ki_titel "$1")"
}

schritt_standard() {
  titel "Standard-KI"
  alle_zustaende
  local jetzt anzahl vorschlag="" i n w="" wahl="" vorwahl=1 teil
  jetzt="$(std_aus_config)"
  anzahl=0; for n in $BEREIT; do anzahl=$((anzahl + 1)); done
  if [ -n "$STANDARD" ]; then
    standard_setzen "$STANDARD"
    if ! ist_bereit "$STANDARD"; then warn "$(ki_titel "$STANDARD") ist noch nicht bereit."; fi
  fi
  if [ "$anzahl" = 0 ]; then
    warn "Ohne KI kann gen_Ut nichts erzeugen. Später: im Tool oben auf eine KI klicken oder ./setup.sh --nur gemini"
  fi
  if [ -n "$STANDARD" ] || [ "$anzahl" = 0 ]; then return 0; fi
  # vorhandene config.toml: die bisherige Standard-KI bleibt, solange sie bereit ist (FR-017)
  if [ "$CONFIG_NEU" = 0 ] && ist_bereit "$jetzt"; then
    vorschlag="$jetzt"
    if [ -n "$NUR" ] || [ "$anzahl" = 1 ] || [ "$INTERAKTIV" = 0 ]; then ok "Standard-KI bleibt $(ki_titel "$jetzt")"; return 0; fi
  else
    vorschlag="$(ki standard-vorschlag --json 2>/dev/null | "$PYBIN" -c 'import json, sys
print(json.load(sys.stdin).get("standard") or "")' 2>/dev/null)" || true
    [ -n "$vorschlag" ] || vorschlag="${BEREIT%% *}"
    if [ -n "$ALT_VORSCHLAG" ] && ist_bereit "$ALT_VORSCHLAG"; then vorschlag="$ALT_VORSCHLAG"; fi
    if [ -n "$NUR" ]; then
      teil="$(ki_name "$NUR")"
      if ist_bereit "$teil"; then vorschlag="$teil"; fi
    fi
    if [ "$CONFIG_NEU" = 1 ] && { [ "$anzahl" = 1 ] || [ "$INTERAKTIV" = 0 ]; }; then standard_setzen "$vorschlag"; return 0; fi
    if [ "$CONFIG_NEU" = 0 ] && { [ "$anzahl" = 1 ] || [ -n "$NUR" ]; }; then
      if frage "Standard-KI auf $(ki_titel "$vorschlag") umstellen? (bisher: $(ki_titel "$jetzt"), nicht bereit)"; then
        standard_setzen "$vorschlag"
      else
        warn "Standard-KI bleibt $(ki_titel "$jetzt") (nicht bereit). Umstellen: im Tool oben oder ./setup.sh --standard …"
      fi
      return 0
    fi
    if [ "$INTERAKTIV" = 0 ]; then
      warn "Standard-KI bleibt $(ki_titel "$jetzt") (nicht bereit). Umstellen: im Tool oben oder ./setup.sh --standard …"
      return 0
    fi
  fi
  # mehrere bereit, mit Terminal: Auswahl mit Vorwahl
  echo "Mehrere KIs sind bereit. Welche soll neue Projekte erzeugen? (im Tool jederzeit umschaltbar)"
  i=0
  for n in claude_code gemini ollama; do
    if ist_bereit "$n"; then
      i=$((i + 1))
      if [ "$n" = "$vorschlag" ]; then vorwahl="$i"; fi
      echo "  $i) $(ki_titel "$n")$(if [ "$n" = "$jetzt" ] && [ "$CONFIG_NEU" = 0 ]; then echo " (bisher)"; fi)"
    fi
  done
  read -r -p "Auswahl [Enter = $vorwahl]: " w < /dev/tty || w=""
  w="${w:-$vorwahl}"
  i=0
  for n in claude_code gemini ollama; do
    if ist_bereit "$n"; then i=$((i + 1)); if [ "$i" = "$w" ]; then wahl="$n"; fi; fi
  done
  if [ -z "$wahl" ]; then warn "Keine gültige Nummer – nehme $(ki_titel "$vorschlag")."; wahl="$vorschlag"; fi
  standard_setzen "$wahl"
}

zusammenfassung() {
  local n z u bereit="" fehlt="" problem="" t
  while IFS="$US" read -r n z u; do
    if [ -z "$n" ]; then continue; fi
    t="$(ki_titel "$n")"
    if [ "$n" = ollama ]; then t="$t (experimentell)"; fi
    case "$z" in
      bereit) bereit="$bereit, $t" ;;
      problem) problem="$problem, $t${u:+ – $u}" ;;
      *) fehlt="$fehlt, $t" ;;
    esac
  done <<EOF
$ZUSTAENDE
EOF
  echo
  if [ -n "$bereit" ]; then ok "bereit: ${bereit#, }"; else warn "bereit: keine"; fi
  if [ -n "$fehlt" ]; then info "nicht eingerichtet: ${fehlt#, }"; fi
  if [ -n "$problem" ]; then warn "Problem: ${problem#, }"; fi
  if [ -n "$fehlt$problem" ]; then
    info "Fehlende KIs kannst du später im Tool einrichten: oben im KI-Schalter auf die KI klicken."
  fi
}

# ---------------------------------------------------------------- KI-Schritte
ZUSTAENDE=""; BEREIT=""
if [ "$KI_DA" = 1 ]; then
  if [ -z "$NUR" ] || [ "$NUR" = claude ]; then schritt_claude; fi
  if [ -z "$NUR" ] || [ "$NUR" = gemini ]; then schritt_gemini; fi
  if [ -z "$NUR" ] || [ "$NUR" = lokal ]; then schritt_lokal; fi
  schritt_standard
else
  titel "KI"
  warn "Die KI-Einrichtung fehlt in dieser Version – Claude, Gemini und Lokal bitte selbst einrichten (siehe README)."
fi

# ---------------------------------------------------------------- Startbefehl
titel "Startbefehl"
PFAD_EXTRA=""
if [ "$NODE_BIN" != "$WURZEL/.werkzeuge/node/bin" ]; then PFAD_EXTRA="$NODE_BIN"; fi
OLLAMA_START=0
if ollama_finden; then
  # nur wenn ein lokales Modell eingetragen ist (sonst braucht gen_Ut Ollama nicht)
  if [ -n "$("$PYBIN" -c 'from genut.config import laden; print((laden().get("ollama") or {}).get("modell") or "")' 2>/dev/null || true)" ]; then
    OLLAMA_START=1
    case ":$PFAD_EXTRA:" in *":$OLLAMA_DIR:"*) ;; *) PFAD_EXTRA="${PFAD_EXTRA:+$PFAD_EXTRA:}$OLLAMA_DIR" ;; esac
  fi
fi
{
  echo '#!/usr/bin/env bash'
  echo '# gen_Ut starten (angelegt von setup.sh). Beenden mit Strg+C.'
  echo 'cd "$(dirname "$0")"'
  if [ -n "$PFAD_EXTRA" ]; then
    # beim Setup gefundenes Node.js/Ollama (z. B. Homebrew) – per Doppelklick im Finder ist der PATH nicht immer derselbe
    echo "export PATH=\"$PFAD_EXTRA:\$PATH\""
  fi
  if [ "$OLLAMA_START" = 1 ]; then
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

if [ "$KI_DA" = 1 ]; then zusammenfassung; fi
printf '\n%sFertig!%s gen_Ut ist eingerichtet.\n' "$G$B" "$N"
echo "Starten:  ./start.sh   – dann öffnet sich gen_Ut im Browser."
