# gen_Ut – Einrichtung für Windows
#
#   setup.bat                                 (Doppelklick) alles einrichten, fragt nach Claude, Gemini und Lokal
#   setup.bat -Nur lokal                      Schalter reicht setup.bat weiter (auch --nur lokal wie bei setup.sh)
#   powershell -ExecutionPolicy Bypass -File setup.ps1 -Nur gemini
#
# Installiert nichts systemweit. Python und Node.js landen bei Bedarf im Benutzer- bzw. Projektordner (keine
# Admin-Rechte nötig). Danach fragt das Setup der Reihe nach Claude, Gemini und ein lokales Modell ab (jeweils
# überspringbar) und zum Schluss die Standard-KI für neue Projekte. Was sich in Python prüfen lässt (Zustand,
# Modellvorschläge, Schlüssel), fragt es über `python -m genut ki …` ab (specs/005b-ein-genut/contracts/cli.md).
# Ablauf wie setup.sh. Läuft mit Windows PowerShell 5.1 und PowerShell 7.
#
# Bewusst ohne param()-Block: Die Schalter werden von Hand gelesen, damit auch die Schreibweise von setup.sh
# (--nur lokal, --nur=lokal) über setup.bat ankommt.
#
# Hinweise für Windows PowerShell 5.1: keine typografischen Anführungszeichen in Zeichenketten (PowerShell hält
# sie für normale), Programme mit Leerzeichen im Pfad über Ausfuehren, Ausgabe von Programmen in Funktionen
# mit Rückgabewert immer abfangen (sonst wird sie Teil des Rückgabewerts).

$ErrorActionPreference = "Continue"        # Fehler werden ausdrücklich geprüft (PS 5.1 bricht sonst bei stderr ab)
$ProgressPreference = "SilentlyContinue"   # Invoke-WebRequest ist sonst sehr langsam
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch { }
Set-Location -LiteralPath $PSScriptRoot
$Wurzel = (Get-Location).Path
$Utf8 = New-Object System.Text.UTF8Encoding($false)   # ohne BOM

# Python spricht UTF-8 (wie "set PYTHONUTF8=1" in start.bat), PowerShell schreibt und liest ebenso:
# $OutputEncoding gilt für Text, der über stdin an Programme geht (der Gemini-Schlüssel; PS 5.1 nimmt sonst ASCII),
# [Console]::OutputEncoding für das Lesen ihrer Ausgabe (sonst die OEM-Codepage, Umlaute würden verstümmelt).
$env:PYTHONUTF8 = "1"
$OutputEncoding = $Utf8
$AlteKonsole = $null
try { $AlteKonsole = [Console]::OutputEncoding; [Console]::OutputEncoding = $Utf8 } catch { $AlteKonsole = $null }

$Interaktiv = $false   # wird nach den Schaltern bestimmt

# ---------------------------------------------------------------- Ausgabe
function Titel([string]$t) { Write-Host ""; Write-Host "== $t ==" -ForegroundColor White }
function Info([string]$t)  { Write-Host "> $t" -ForegroundColor Cyan }
function Ok([string]$t)    { Write-Host "OK $t" -ForegroundColor Green }
function Warn([string]$t)  { Write-Host "!  $t" -ForegroundColor Yellow }
function Beenden([int]$code) {
    if ($Interaktiv) { Read-Host "Enter zum Schließen" | Out-Null }
    if ($AlteKonsole) { try { [Console]::OutputEncoding = $AlteKonsole } catch { } }
    exit $code
}
function Abbruch([string]$t) {
    Write-Host "X  $t" -ForegroundColor Red
    Beenden 1
}

function Hilfe {
    Write-Output @'
gen_Ut – Einrichtung für Windows

  setup.bat                                  alles einrichten, fragt nach Claude, Gemini und Lokal
  .\setup.ps1 -Nur claude|gemini|lokal       nur diesen Teil nachholen
  .\setup.ps1 -Standard claude|gemini|lokal  Standard-KI für neue Projekte vorgeben
  .\setup.ps1 -LokalModell gemma3:4b         lokales Modell ohne Rückfrage laden
  .\setup.ps1 -Ja                            Rückfragen zu Python und Node.js mit "ja" beantworten
                                             (installiert Claude oder Ollama nur zusammen mit
                                             -Nur claude, -Nur lokal oder -LokalModell)
  .\setup.ps1 -Version claude                alt, nur Vorschlag für die Standard-KI
  .\setup.ps1 -Hilfe                         diese Hilfe

setup.bat reicht dieselben Schalter weiter (setup.bat -Nur lokal, auch --nur lokal wie bei setup.sh).
Sperrt Windows .\setup.ps1 (Ausführungsrichtlinie), geht immer:
  powershell -ExecutionPolicy Bypass -File setup.ps1 -Nur lokal

Ohne Konsole (z. B. in Tests) fragt das Setup nichts und richtet nur ein, was vorgegeben ist:
GEMINI_API_KEY als Umgebungsvariable, -LokalModell, -Standard.
'@
}

# ---------------------------------------------------------------- Schalter
# -Nur lokal, --nur lokal, --nur=lokal, -Nur:lokal; Groß- und Kleinschreibung egal
$Nur = ""; $Standard = ""; $LokalModell = ""; $AltVersion = ""; $AltVorschlag = ""; $Ja = $false
$Rest = @($args)
$i = 0
while ($i -lt $Rest.Count) {
    $roh = [string]$Rest[$i]
    $name = $roh; $wert = $null
    if ($roh -match '^(--?[A-Za-z][A-Za-z-]*)[=:](.*)$') {
        $name = $Matches[1]
        if ($Matches[2] -ne "") { $wert = $Matches[2] }
    }
    $schalter = ""
    if ($name.StartsWith("-")) { $schalter = ($name -replace "-", "").ToLowerInvariant() }
    if (@("nur", "standard", "lokalmodell", "version") -contains $schalter) {
        if ($null -eq $wert) {
            if ($i + 1 -ge $Rest.Count -or ([string]$Rest[$i + 1]) -eq "") { Abbruch "$name braucht einen Wert (Hilfe: .\setup.ps1 -Hilfe)" }
            $i++
            $wert = [string]$Rest[$i]
        }
        if ($schalter -eq "nur") { $Nur = $wert.ToLowerInvariant() }
        elseif ($schalter -eq "standard") { $Standard = $wert.ToLowerInvariant() }
        elseif ($schalter -eq "lokalmodell") { $LokalModell = $wert }
        else { $AltVersion = $wert.ToLowerInvariant() }
    } elseif (@("ja", "yes", "y") -contains $schalter) {
        $Ja = $true
    } elseif (@("hilfe", "help", "h") -contains $schalter -or $roh -eq "/?") {
        Hilfe
        Beenden 0
    } else {
        Abbruch "Unbekannte Option: $roh (Hilfe: .\setup.ps1 -Hilfe)"
    }
    $i++
}

# claude | gemini | lokal (auch die internen Namen) -> Name in config.toml
function KiName([string]$n) {
    switch ($n) {
        "claude" { return "claude_code" }
        "claude_code" { return "claude_code" }
        "gemini" { return "gemini" }
        "lokal" { return "ollama" }
        "ollama" { return "ollama" }
    }
    return ""
}
function KiTitel([string]$n) {
    switch ($n) {
        "claude_code" { return "Claude" }
        "gemini" { return "Gemini" }
        "ollama" { return "Lokal" }
    }
    return $n
}

if (@("", "claude", "gemini", "lokal") -notcontains $Nur) { Abbruch "-Nur kennt claude, gemini und lokal (nicht '$Nur')" }
if ($Standard) {
    if (-not (KiName $Standard)) { Abbruch "-Standard kennt claude, gemini und lokal (nicht '$Standard')" }
    $Standard = KiName $Standard
}
if ($LokalModell -match '[^A-Za-z0-9._:/-]') { Abbruch "Ungültiger Modellname '$LokalModell'" }
if ($AltVersion) {
    if (-not (KiName $AltVersion)) {
        Warn "-Version gibt es nicht mehr, es gibt nur noch ein gen_Ut mit allen KIs. '$AltVersion' wird ignoriert."
    } elseif ($Standard) {
        Warn "-Version ist veraltet und wird neben -Standard ignoriert."
    } else {
        $AltVorschlag = KiName $AltVersion
        Warn "-Version ist veraltet: '$AltVersion' gilt nur noch als Vorschlag für die Standard-KI (alle KIs werden abgefragt)."
    }
}

# Interaktiv nur mit Konsole (stdin nicht umgeleitet, nicht -NonInteractive); -Ja beantwortet nur die Rückfragen
# zur Umgebung. In Tests: stdin umleiten (z. B. "" | powershell -File setup.ps1 …) oder -NonInteractive.
if (-not $Ja) {
    $umgeleitet = $true
    try { $umgeleitet = [Console]::IsInputRedirected } catch { $umgeleitet = $true }
    $nichtInteraktiv = @([Environment]::GetCommandLineArgs() | Where-Object { "$_" -match '^-noni' }).Count -gt 0
    if (-not $umgeleitet -and -not $nichtInteraktiv -and [Environment]::UserInteractive) { $Interaktiv = $true }
}

function Frage([string]$text, [string]$vorgabe = "j") {   # -> $true = ja; j/n ist die Antwort bei Enter
    if ($Ja) { return $true }
    if (-not $Interaktiv) { return $false }
    if ($vorgabe -eq "j") { $a = Read-Host "$text [J/n]" } else { $a = Read-Host "$text [j/N]" }
    if ("$a" -match '^[jJyY]') { return $true }
    if ("$a" -match '^[nN]') { return $false }
    return ($vorgabe -eq "j")
}

# Teil ausdrücklich verlangt (-Nur …, für Lokal auch -LokalModell)?
function Explizit([string]$teil) {
    if ($Nur -eq $teil) { return $true }
    if ($teil -eq "lokal" -and $LokalModell) { return $true }
    return $false
}

# Installation von Claude oder Ollama: interaktiv nach Rückfrage, ohne Konsole nur mit -Ja und ausdrücklichem Teil
function InstallierenErlaubt([string]$text, [string]$teil, [string]$vorgabe = "j") {
    if ($Interaktiv) { return (Frage $text $vorgabe) }
    if ($Ja -and (Explizit $teil)) { Info "$text - ja (-Ja)"; return $true }
    return $false
}

function Laden([string]$url, [string]$ziel) { Invoke-WebRequest -Uri $url -OutFile $ziel -UseBasicParsing -ErrorAction Stop }
function Befehl([string]$name) {
    $c = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c) { return $c.Path }
    return $null
}
function PfadErgaenzen([string]$ordner) {   # Ordner vorne in den PATH dieser Sitzung
    if (-not $ordner) { return }
    $teile = @($env:Path -split ";" | Where-Object { $_ } | ForEach-Object { $_.TrimEnd([char]92) })
    if ($teile -notcontains $ordner.TrimEnd([char]92)) { $env:Path = "$ordner;$env:Path" }
}
function PfadNeuLaden {   # nach einem Installer: PATH aus der Registry dazunehmen (Ergänzungen dieser Sitzung bleiben)
    $env:Path = $env:Path + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}
function BrowserOeffnen([string]$url) { try { Start-Process $url -ErrorAction Stop | Out-Null } catch { } }

# Programm im selben Fenster starten (Ein- und Ausgabe direkt an der Konsole, z. B. für Fortschrittsbalken und
# die Anmeldung bei Claude), warten, Exit-Code zurückgeben. Start-Process setzt die Argumente nur mit
# Leerzeichen zusammen, deshalb werden solche mit Leerzeichen hier in Anführungszeichen gesetzt.
function Ausfuehren([string]$exe, [string[]]$argumente) {
    $teile = @($argumente | Where-Object { $null -ne $_ } | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } })
    try {
        if ($teile.Count -gt 0) {
            $p = Start-Process -FilePath $exe -ArgumentList ($teile -join " ") -NoNewWindow -PassThru -ErrorAction Stop
        } else {
            $p = Start-Process -FilePath $exe -NoNewWindow -PassThru -ErrorAction Stop
        }
        $null = $p.Handle   # sonst ist ExitCode unter PS 5.1 manchmal leer
        $p.WaitForExit()
        return [int]$p.ExitCode
    } catch {
        Warn "$exe ließ sich nicht starten: $_"
        return -1
    }
}

# Offizielle Installer (irm … | iex) in einer eigenen PowerShell: ein "exit" darin beendet nicht dieses Setup.
$PsExe = (Get-Process -Id $PID).Path
function InstallerAusfuehren([string]$url, [string]$name) {   # -> $true, wenn der Installer mit 0 endet
    $skript = Join-Path $Wurzel ".werkzeuge\$name-install.ps1"
    try {
        $inhalt = Invoke-RestMethod -Uri $url -ErrorAction Stop
        [IO.File]::WriteAllText($skript, ([string]$inhalt).TrimStart([char]0xFEFF), (New-Object System.Text.UTF8Encoding($true)))
    } catch {
        Warn "Der Installer ließ sich nicht laden ($url): $_"
        return $false
    }
    $code = Ausfuehren $PsExe @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $skript)
    Remove-Item -LiteralPath $skript -Force -ErrorAction SilentlyContinue
    PfadNeuLaden
    return ($code -eq 0)
}

Write-Host "gen_Ut – Einrichtung (Windows)" -ForegroundColor White

# ---------------------------------------------------------------- Version (versionen/AKTIV)
$Aktiv = ""
$aktivDatei = Join-Path $Wurzel "versionen\AKTIV"
if (Test-Path -LiteralPath $aktivDatei) {
    # UTF-8-sicher einlesen (BOM wird erkannt und entfernt), erste nicht leere Zeile
    $Aktiv = [string]([IO.File]::ReadAllLines($aktivDatei, $Utf8) | ForEach-Object { $_.Trim([char]0xFEFF).Trim() } | Where-Object { $_ } | Select-Object -First 1)
}
if ($Aktiv -eq "schule") {
    Info "Die Schul-Version läuft als Docker-Image auf einem Server, den ein Admin betreibt."
    Info "Dieses Setup richtet sie nicht ein. Anleitung: docs\schule\"
    Beenden 0
}

# ---------------------------------------------------------------- Python
Titel "Python"
New-Item -ItemType Directory -Force -Path ".werkzeuge" | Out-Null
$VenvPy = Join-Path $Wurzel ".venv\Scripts\python.exe"
$PyOk = "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
function VenvOk {
    if (-not (Test-Path -LiteralPath $VenvPy)) { return $false }
    & $VenvPy -c $PyOk 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}
function UvFinden {
    $u = Befehl "uv"; if ($u) { return $u }
    foreach ($k in @("$env:USERPROFILE\.local\bin\uv.exe", "$env:USERPROFILE\.cargo\bin\uv.exe")) { if (Test-Path -LiteralPath $k) { return $k } }
    return $null
}

if (VenvOk) {
    Ok "Python-Umgebung .venv ist schon da ($(& $VenvPy --version))"
} else {
    if (Test-Path ".venv") { Remove-Item -Recurse -Force ".venv" }
    # 1. Python-Launcher "py", 2. python.exe (nicht der Microsoft-Store-Platzhalter)
    $Py = $null
    foreach ($kandidat in @(@("py", "-3"), @("python"))) {
        $exe = Befehl $kandidat[0]
        if (-not $exe -or $exe -like "*WindowsApps*") { continue }
        $argumente = @(); if ($kandidat.Count -gt 1) { $argumente = $kandidat[1..($kandidat.Count - 1)] }
        & $exe @argumente -c $PyOk 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { $Py = @($exe) + $argumente; break }
    }
    $angelegt = $false
    if ($Py) {
        $exe = $Py[0]; $argumente = @(); if ($Py.Count -gt 1) { $argumente = $Py[1..($Py.Count - 1)] }
        & $exe @argumente -m venv .venv 2>$null | Out-Null
        $angelegt = VenvOk
    }
    if ($angelegt) {
        Ok "Python-Umgebung mit $(& $VenvPy --version) angelegt"
    } else {
        if (Test-Path ".venv") { Remove-Item -Recurse -Force ".venv" }
        Warn "Kein passendes Python 3.11 oder neuer gefunden."
        $Uv = UvFinden
        if (-not $Uv) {
            if (-not (Frage "Python über 'uv' in deinen Benutzerordner installieren (ohne Admin-Rechte, ca. 50 MB)?")) {
                Abbruch "Ohne Python geht es nicht. Installiere Python 3.11+ von https://www.python.org (Haken bei 'Add Python to PATH') und starte das Setup neu."
            }
            if (-not (InstallerAusfuehren "https://astral.sh/uv/install.ps1" "uv")) { Warn "Der uv-Installer meldet einen Fehler." }
            $Uv = UvFinden
            if (-not $Uv) { Abbruch "uv konnte nicht installiert werden." }
        }
        Info "Lade Python 3.12 und lege .venv an …"
        & $Uv venv --python 3.12 .venv 2>&1 | Out-Null
        & $Uv pip install --python $VenvPy pip 2>&1 | Out-Null
        if (-not (VenvOk)) { Abbruch "Die Python-Umgebung funktioniert nicht." }
        Ok "Python-Umgebung mit $(& $VenvPy --version) angelegt"
    }
}

$genutDa = $false
if ($Nur) { & $VenvPy -c "import genut" 2>$null | Out-Null; $genutDa = ($LASTEXITCODE -eq 0) }
if ($genutDa) {
    Ok "Python-Pakete sind schon installiert"
} else {
    Info "Installiere die Python-Pakete (beim ersten Mal ein paar Minuten) …"
    & $VenvPy -m pip install --disable-pip-version-check -e . *> ".werkzeuge\pip.log"
    if ($LASTEXITCODE -ne 0) {
        Get-Content ".werkzeuge\pip.log" -Tail 25
        Abbruch "pip install ist fehlgeschlagen (ganzes Protokoll: .werkzeuge\pip.log)."
    }
    Ok "Python-Pakete installiert"
}

# ---------------------------------------------------------------- Node.js
Titel "Node.js"
$NodeExe = Join-Path $Wurzel ".werkzeuge\node\node.exe"
$NodeDir = $null
function NodeLaeuft([string]$exe) {
    if (-not $exe -or -not (Test-Path -LiteralPath $exe)) { return $false }
    & $exe --version 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}
if (NodeLaeuft $NodeExe) {
    $NodeDir = Split-Path $NodeExe
} else {
    $sys = Befehl "node"
    $sysOk = $false
    if ($sys -and (Befehl "npm")) {
        & $sys -e "process.exit(+process.versions.node.split('.')[0] >= 20 ? 0 : 1)" 2>$null | Out-Null
        $sysOk = ($LASTEXITCODE -eq 0)
    }
    if ($sysOk) {
        $NodeDir = Split-Path $sys
    } else {
        if ($sys) { Warn "Node.js $(& $sys --version) ist zu alt (mindestens 20)." } else { Warn "Node.js fehlt." }
        if (-not (Frage "Node.js (LTS) in den gen_Ut-Ordner herunterladen (ohne Admin-Rechte, ca. 30 MB)?")) {
            Abbruch "Ohne Node.js geht es nicht. Installiere es von https://nodejs.org und starte das Setup neu."
        }
        $arch = "x64"; if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { $arch = "arm64" }
        try { $index = Invoke-RestMethod -Uri "https://nodejs.org/dist/index.json" -ErrorAction Stop } catch { Abbruch "Keine Verbindung zu nodejs.org: $_" }
        # neueste LTS je Hauptversion (ab 20), neueste zuerst
        $versionen = @(); $gesehen = @{}
        foreach ($r in $index) {
            $major = [int]($r.version.TrimStart("v").Split(".")[0])
            if ($r.lts -and $major -ge 20 -and -not $gesehen.ContainsKey($major)) { $gesehen[$major] = $true; $versionen += $r.version }
        }
        foreach ($nv in $versionen) {
            Info "Lade Node.js $nv …"
            $zip = ".werkzeuge\node.zip"
            try { Laden "https://nodejs.org/dist/$nv/node-$nv-win-$arch.zip" $zip } catch { Warn "Download fehlgeschlagen."; continue }
            if (Test-Path ".werkzeuge\node") { Remove-Item -Recurse -Force ".werkzeuge\node" }
            Expand-Archive -Path $zip -DestinationPath ".werkzeuge" -Force
            Remove-Item $zip
            Rename-Item ".werkzeuge\node-$nv-win-$arch" "node"
            if (NodeLaeuft $NodeExe) { $NodeDir = Split-Path $NodeExe; break }
            Warn "Node.js $nv startet hier nicht – probiere eine ältere Version."
        }
        if (-not $NodeDir) { Abbruch "Keine Node.js-Version läuft hier. Bitte Node.js 20+ von https://nodejs.org installieren." }
    }
}
Ok "Node.js $(& (Join-Path $NodeDir 'node.exe') --version)"
$env:Path = "$NodeDir;$env:Path"
if ($Nur -and (Test-Path -LiteralPath "node_modules")) {
    Ok "Node-Pakete sind schon installiert"
} else {
    Info "Installiere die Node-Pakete (MathJax, Mermaid, sql.js, PDFKit) …"
    & (Join-Path $NodeDir "npm.cmd") ci --no-audit --no-fund --loglevel=error *> ".werkzeuge\npm.log"
    if ($LASTEXITCODE -ne 0) {
        Get-Content ".werkzeuge\npm.log" -Tail 25
        Abbruch "npm ci ist fehlgeschlagen (Protokoll: .werkzeuge\npm.log)."
    }
    Ok "Node-Pakete installiert"
}

# ---------------------------------------------------------------- Hilfen für die KI-Schritte
$KiDa = $false
& $VenvPy -m genut ki --help 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) { $KiDa = $true }

function Zeilen($ausgabe) {   # Ausgabe eines Programms (auch stderr-Zeilen aus 2>&1) als ein Text
    return ((@($ausgabe) | ForEach-Object { "$_" }) -join " ").Trim()
}
function JsonLesen($ausgabe) {
    $text = (@($ausgabe) | ForEach-Object { "$_" }) -join "`n"
    if (-not $text.Trim()) { return $null }
    try { return ($text | ConvertFrom-Json -ErrorAction Stop) } catch { return $null }
}

function StdAusConfig([string]$datei) {
    if (-not (Test-Path -LiteralPath $datei)) { return "" }
    $m = Select-String -LiteralPath $datei -Pattern '^standard\s*=\s*"([a-z_]+)"' -Encoding UTF8 | Select-Object -First 1
    if ($m) { return $m.Matches[0].Groups[1].Value }
    return ""
}

# Zustand einer KI: Zustand (bereit|nicht_eingerichtet|problem), Ursache, Aktion, Befehl (voller Pfad, nur Claude)
function KiZustand([string]$name) {
    $roh = & $VenvPy -m genut ki zustand --json $name 2>$null
    $d = JsonLesen $roh
    $z = [pscustomobject]@{ Zustand = "problem"; Ursache = "Prüfung fehlgeschlagen"; Aktion = ""; Befehl = "" }
    if ($d -and $d.zustand) {
        $z.Zustand = [string]$d.zustand
        $z.Ursache = [string]$d.ursache
        $z.Aktion = [string]$d.aktion
        $z.Befehl = [string]$d.befehl
    }
    return $z
}

# alle Zustände -> $script:Zustaende (name, zustand, ursache in der Reihenfolge von auswahl), $script:Bereit (Namen)
$Zustaende = @(); $Bereit = @()
function AlleZustaende {
    $roh = & $VenvPy -m genut ki zustand --json 2>$null
    $d = JsonLesen $roh
    $script:Zustaende = @()
    if ($d -and $d.zustaende) { $script:Zustaende = @($d.zustaende) }
    $script:Bereit = @($script:Zustaende | Where-Object { $_.zustand -eq "bereit" } | ForEach-Object { [string]$_.name })
}
function IstBereit([string]$n) { return ($n -and ($script:Bereit -contains $n)) }

function KiSetzen([string]$schluessel, [string]$wert) {   # -> $true bei Erfolg
    & $VenvPy -m genut ki setzen $schluessel $wert 2>&1 | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function KonfigModell {   # [ollama] modell aus config.toml
    $m = & $VenvPy -c "from genut.config import laden; print((laden().get('ollama') or {}).get('modell') or '')" 2>$null
    return (Zeilen $m)
}

# ---------------------------------------------------------------- config.toml
Titel "Konfiguration"
$Vorlage = "genut"
if ($Aktiv -eq "" -or $Aktiv -eq "genut") {
} elseif (@("claude", "gemini", "lokal") -contains $Aktiv) {
    Info "versionen\AKTIV nennt die alte Version '$Aktiv' – es gibt nur noch genut mit allen KIs."
} elseif ($Aktiv -match '^[A-Za-z0-9_-]+$' -and (Test-Path -LiteralPath "versionen\$Aktiv.toml")) {
    $Vorlage = $Aktiv
} else {
    Warn "versionen\$Aktiv.toml fehlt – nehme versionen\genut.toml."
}
$ConfigNeu = $false
if (-not (Test-Path -LiteralPath "config.toml")) {
    if (-not (Test-Path -LiteralPath "versionen\$Vorlage.toml")) { Abbruch "versionen\$Vorlage.toml fehlt (ist das der gen_Ut-Ordner?)" }
    Copy-Item -LiteralPath "versionen\$Vorlage.toml" -Destination "config.toml"
    $ConfigNeu = $true
    Ok "config.toml angelegt (Vorlage: versionen\$Vorlage.toml)"
} elseif ($KiDa) {
    # vorhandene Datei: nur fehlende KIs in [modell] auswahl ergänzen (vorher config.toml.bak), sonst nichts ändern
    $ausgabe = & $VenvPy -m genut ki auswahl-ergaenzen 2>&1
    $code = $LASTEXITCODE
    $meldung = Zeilen $ausgabe
    if ($code -eq 0) {
        if ($meldung -like "*nzt:*") { Ok "$meldung (Sicherung: config.toml.bak)" } else { Ok "config.toml ist schon da ($meldung)" }
    } else {
        Warn "config.toml ließ sich nicht ergänzen: $meldung"
    }
} else {
    Ok "config.toml ist schon da"
}

# ---------------------------------------------------------------- Claude
function ClaudePfadEintragen($z) {   # liegt die CLI nicht im Suchpfad, kommt ihr voller Pfad in config.toml
    if ($z.Befehl -and -not (Befehl "claude")) {
        if (KiSetzen "claude_code.befehl" $z.Befehl) { Info "Voller Pfad in config.toml eingetragen: $($z.Befehl)" }
    }
}

function ClaudeAnmelden($z) {
    $cl = $z.Befehl; if (-not $cl) { $cl = "claude" }
    if (-not $Interaktiv) {
        Warn "Melde dich einmal an (Claude-Abo Pro oder höher): in einem Terminal '$cl' starten, anmelden, mit /exit beenden."
        return
    }
    Info "Zum Anmelden startet Claude in diesem Fenster: folge der Anmeldung (Browser), danach mit /exit beenden."
    if (Frage "Claude jetzt zum Anmelden starten?") {
        $exe = $z.Befehl; if (-not $exe) { $exe = Befehl "claude" }
        if ($exe) { Ausfuehren $exe @() | Out-Null }
        $z2 = KiZustand "claude_code"
        if ($z2.Zustand -eq "bereit") { Ok "Claude ist angemeldet und bereit"; return }
    }
    Warn "Claude ist noch nicht angemeldet. Später: in einem Terminal '$cl' starten und anmelden."
}

function GitPruefen {   # Claude Code braucht unter Windows Git for Windows (Git Bash)
    if (Befehl "git") { return }
    Warn "Claude Code braucht unter Windows 'Git for Windows'."
    $winget = Befehl "winget"
    if ($winget -and (InstallierenErlaubt "Git for Windows mit winget installieren?" "claude")) {
        $code = Ausfuehren $winget @("install", "--id", "Git.Git", "-e", "--source", "winget", "--accept-package-agreements", "--accept-source-agreements")
        if ($code -ne 0) { Warn "winget meldet einen Fehler (Code $code)." }
        PfadNeuLaden
    } else {
        Warn "Bitte Git von https://git-scm.com/download/win installieren."
    }
}

function SchrittClaude {
    Titel "Claude"
    $z = KiZustand "claude_code"
    if ($z.Zustand -eq "bereit") {
        if ($z.Befehl) { Ok "Claude gefunden: $($z.Befehl)" } else { Ok "Claude gefunden" }
        ClaudePfadEintragen $z
        return
    }
    if ($z.Zustand -eq "problem") {
        ClaudePfadEintragen $z
        if ($z.Aktion -eq "anmelden") {
            Warn "Claude ist installiert, aber nicht angemeldet."
            ClaudeAnmelden $z
        } else {
            $u = $z.Ursache; if (-not $u) { $u = "unbekannt" }
            Warn "Claude: Problem ($u)."
        }
        return
    }
    if ($Interaktiv) { Info "Claude braucht ein Claude-Abo (Pro oder höher) und liefert die beste Qualität." }
    $vorgabe = "n"; if (Explizit "claude") { $vorgabe = "j" }
    if (-not (InstallierenErlaubt "Claude einrichten (offizieller Installer von claude.ai, ohne Admin-Rechte)?" "claude" $vorgabe)) {
        Info "Claude übersprungen. Später: im Tool oben auf Claude klicken oder .\setup.ps1 -Nur claude"
        return
    }
    GitPruefen
    Info "Installiere Claude Code …"
    if (-not (InstallerAusfuehren "https://claude.ai/install.ps1" "claude")) { Warn "Die Installation meldet einen Fehler." }
    $z = KiZustand "claude_code"
    if ($z.Zustand -eq "nicht_eingerichtet") {
        Warn "Claude Code wurde nicht gefunden. Anleitung: https://claude.com/claude-code"
        return
    }
    if ($z.Befehl) { Ok "Claude Code installiert: $($z.Befehl)" } else { Ok "Claude Code installiert" }
    ClaudePfadEintragen $z
    if ($z.Zustand -eq "bereit") { Ok "Claude ist bereit" } else { ClaudeAnmelden $z }
}

# ---------------------------------------------------------------- Gemini
# Der Schlüssel geht nur über stdin an Python (nie als Argument). $OutputEncoding ist UTF-8 ohne BOM;
# PowerShell hängt einen Zeilenumbruch an, Python entfernt ihn (und ein BOM, falls doch eines kommt).
function GeminiPruefen([string]$key) {   # -> 0 gespeichert, 1 abgelehnt, 3 keine Verbindung
    $ausgabe = $key | & $VenvPy -m genut ki gemini-pruefen 2>&1
    $code = $LASTEXITCODE
    $meldung = Zeilen $ausgabe
    if ($code -eq 0) { Ok $meldung } else { Warn $meldung }
    return [int]$code
}

function GeminiUngeprueftSpeichern([string]$key) {   # -> $true bei Erfolg
    $key | & $VenvPy -c "from genut.funktionen.ki_einrichtung import befehle, env; env.schluessel_speichern(befehle._stdin_lesen())" 2>&1 | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function GeminiUmgebungLeeren {   # ab jetzt zählt .env
    Remove-Item -Path "Env:GEMINI_API_KEY" -ErrorAction SilentlyContinue
    Remove-Item -Path "Env:GOOGLE_API_KEY" -ErrorAction SilentlyContinue
}

function SchluesselLesen {   # verdeckte Eingabe, Leerzeichen und Zeilenumbrüche fallen weg
    $s = Read-Host "Schlüssel einfügen (wird nicht angezeigt, Enter = überspringen)" -AsSecureString
    if (-not $s) { return "" }
    $b = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)
    try { return ([string][Runtime.InteropServices.Marshal]::PtrToStringBSTR($b)) -replace '\s', '' } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b) }
}

function GeminiEingeben {   # fragt verdeckt nach dem Schlüssel; bei "abgelehnt" einmal neu
    Write-Host "Gemini ist gratis mit einem Schlüssel von Google AI Studio:"
    Write-Host "  1. https://aistudio.google.com/apikey öffnen und mit einem Google-Konto anmelden"
    Write-Host "  2. 'Create API key' klicken und den Schlüssel kopieren"
    if (Frage "Seite jetzt im Browser öffnen?") { BrowserOeffnen "https://aistudio.google.com/apikey" }
    for ($versuch = 1; $versuch -le 2; $versuch++) {
        $key = SchluesselLesen
        if (-not $key) { Info "Gemini übersprungen. Später: im Tool oben auf Gemini klicken oder .\setup.ps1 -Nur gemini"; return }
        $code = GeminiPruefen $key
        if ($code -eq 0) { GeminiUmgebungLeeren; return }
        if ($code -eq 3) {
            if (Frage "Schlüssel trotzdem ungeprüft speichern?" "n") {
                if (GeminiUngeprueftSpeichern $key) { Ok "Schlüssel ungeprüft in .env gespeichert"; GeminiUmgebungLeeren }
                else { Warn "Schlüssel ließ sich nicht speichern." }
            }
            return
        }
        if ($versuch -lt 2) { Info "Prüfe den Schlüssel auf aistudio.google.com und füge ihn noch einmal ein." }
    }
    Warn "Gemini übersprungen. Später: im Tool oben auf Gemini klicken oder .\setup.ps1 -Nur gemini"
}

function SchrittGemini {
    Titel "Gemini"
    if ($env:GEMINI_API_KEY) {
        Info "Prüfe den Schlüssel aus GEMINI_API_KEY …"
        $code = GeminiPruefen ($env:GEMINI_API_KEY -replace '\s', '')
        if ($code -eq 1 -and $Interaktiv) { GeminiEingeben }
        return
    }
    $z = KiZustand "gemini"
    if ($z.Zustand -eq "bereit") { Ok "Gemini ist bereit (Schlüssel in .env)"; return }
    if ($z.Aktion -ne "schluessel") {
        $u = $z.Ursache; if (-not $u) { $u = "Problem" }
        Warn "Gemini: $u. Der gespeicherte Schlüssel bleibt; später nochmal prüfen."
        return
    }
    if ($z.Zustand -eq "problem") { Warn "Gemini: $($z.Ursache)." }
    if ($Interaktiv) {
        GeminiEingeben
    } else {
        Info "Gemini übersprungen (ohne Konsole nur mit GEMINI_API_KEY=...)."
    }
}

# ---------------------------------------------------------------- Lokal (Ollama)
$Ollama = ""; $OllamaDir = ""
function OllamaFinden {   # -> $true und PATH ergänzt, wenn ollama da ist
    $o = Befehl "ollama"
    if (-not $o -and $env:LOCALAPPDATA) {
        $k = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
        if (Test-Path -LiteralPath $k) { $o = $k; PfadErgaenzen (Split-Path $k) }
    }
    if (-not $o) { return $false }
    $script:Ollama = $o
    $script:OllamaDir = Split-Path $o
    return $true
}
function OllamaLaeuft {
    & $script:Ollama list 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}
function OllamaHat([string]$m) {
    $namen = @(& $script:Ollama list 2>$null | Select-Object -Skip 1 | ForEach-Object { ("$_".Trim() -split '\s+')[0] })
    return (($namen -contains $m) -or ($namen -contains ($m + ":latest")))
}
function OllamaStarten {   # -> $true, wenn Ollama läuft
    if (OllamaLaeuft) { return $true }
    Info "Starte Ollama …"
    try { Start-Process -FilePath $script:Ollama -ArgumentList "serve" -WindowStyle Hidden -ErrorAction Stop | Out-Null } catch { return $false }
    for ($n = 0; $n -lt 10; $n++) {
        if (OllamaLaeuft) { return $true }
        Start-Sleep -Seconds 1
    }
    return (OllamaLaeuft)
}

# OllamaSetup.exe installiert laut https://docs.ollama.com/windows ohne Admin-Rechte nach
# %LOCALAPPDATA%\Programs\Ollama und trägt sich in den Benutzer-PATH ein; diese Sitzung bekommt den Ordner dazu.
function OllamaInstallieren {   # -> $true, wenn Ollama danach da ist
    if (-not (InstallierenErlaubt "Ollama fehlt. Installieren (offizieller Installer von ollama.com, ohne Admin-Rechte, über 1 GB)?" "lokal")) {
        Warn "Ollama fehlt: von https://ollama.com/download installieren, danach .\setup.ps1 -Nur lokal"
        return $false
    }
    $temp = $env:TEMP; if (-not $temp) { $temp = Join-Path $Wurzel ".werkzeuge" }
    $setup = Join-Path $temp "OllamaSetup.exe"
    Info "Lade den Ollama-Installer (das kann eine Weile dauern) …"
    try { Laden "https://ollama.com/download/OllamaSetup.exe" $setup } catch { Warn "Download fehlgeschlagen: $_"; return $false }
    Info "Installiere Ollama …"
    $still = "/SILENT"; if (-not $Interaktiv) { $still = "/VERYSILENT" }
    $code = Ausfuehren $setup @($still, "/NORESTART", "/SUPPRESSMSGBOXES")
    Remove-Item -LiteralPath $setup -Force -ErrorAction SilentlyContinue
    if ($code -ne 0) { Warn "Der Ollama-Installer meldet einen Fehler (Code $code)." }
    if (-not (OllamaFinden)) { Warn "Ollama wurde nach der Installation nicht gefunden."; return $false }
    Ok "Ollama installiert"
    return $true
}

# Vorschläge als nummerierte Liste zeigen und eine Wahl lesen -> $script:Modell, $script:ModellPlatz
$Modell = ""; $ModellPlatz = $false
function ModellWaehlen {
    $script:Modell = ""; $script:ModellPlatz = $false
    $roh = & $VenvPy -m genut ki modelle --json 2>$null
    $d = JsonLesen $roh
    if (-not $d -or -not $d.vorschlaege) { Warn "Die Modellvorschläge ließen sich nicht ermitteln."; return }
    $liste = @($d.vorschlaege)
    $vorwahl = 1
    Write-Host "Modelle, die Fotos verstehen (Urteil für diesen Computer):"
    for ($n = 0; $n -lt $liste.Count; $n++) {
        $v = $liste[$n]
        $gb = ([double]$v.download_gb).ToString("g", [Globalization.CultureInfo]::InvariantCulture).Replace(".", ",")
        $zeile = "  $($n + 1)) $($v.name) ($gb GB) – $($v.begruendung)"
        if ($v.vorgewaehlt) { $zeile += " [Vorwahl]"; $vorwahl = $n + 1 }
        if ($v.vorhanden) { $zeile += " [schon geladen]" } elseif ($v.platz_warnung) { $zeile += " [Speicherplatz knapp]" }
        Write-Host $zeile
    }
    if ($d.keins_gut) { Warn "Kein Modell läuft auf diesem Computer gut. Empfehlung: Gemini. Wählen kannst du trotzdem." }
    $w = Read-Host "Modell wählen [1-$($liste.Count), Enter = $vorwahl, 0 = keins]"
    $w = "$w".Trim()
    if (-not $w) { $w = "$vorwahl" }
    if ($w -eq "0") { return }
    if ($w -match '^[1-9]$') {
        $k = [int]$w
        if ($k -le $liste.Count) {
            $script:Modell = [string]$liste[$k - 1].name
            $script:ModellPlatz = [bool]$liste[$k - 1].platz_warnung
        } else {
            Warn "Keine gültige Nummer – kein Modell gewählt."
        }
        return
    }
    if ($w -match '[^A-Za-z0-9._:/-]') { Warn "Ungültiger Modellname – kein Modell gewählt."; return }
    $script:Modell = $w   # eigener Modellname
}

function SchrittLokal {
    Titel "Lokal (Ollama) – experimentell"
    $z = KiZustand "ollama"
    # installiert, aber nicht gestartet: erst starten, vielleicht ist dann alles da
    if ($z.Aktion -eq "starten" -and ($Interaktiv -or (Explizit "lokal"))) {
        if ((OllamaFinden) -and (OllamaStarten)) { $z = KiZustand "ollama" }
    }
    $jetzt = KonfigModell
    if ($z.Zustand -eq "bereit" -and (-not $LokalModell -or $LokalModell -eq $jetzt)) {
        Ok "Lokal ist bereit (Modell $jetzt)"
        return
    }
    if (-not (Explizit "lokal")) {
        if (-not $Interaktiv) { Info "Lokal übersprungen (ohne Konsole nur mit -LokalModell)."; return }
        Info "Ein lokales Modell läuft auf deinem Computer, ohne Internet – langsamer und einfacher als Claude oder Gemini."
        if (-not (Frage "Lokales Modell einrichten? (experimentell)" "n")) {
            Info "Lokal übersprungen. Später: .\setup.ps1 -Nur lokal"
            return
        }
    }
    if (-not (OllamaFinden)) {
        if (-not (OllamaInstallieren)) { return }
    }
    if (-not (OllamaStarten)) {
        Warn "Ollama startet nicht. Starte die Ollama-App (oder 'ollama serve') und dann .\setup.ps1 -Nur lokal"
        return
    }
    Ok "Ollama läuft"
    $script:Modell = $LokalModell; $script:ModellPlatz = $false
    if (-not $script:Modell) {
        if (-not $Interaktiv) { Info "Kein Modell vorgegeben (-LokalModell) – übersprungen."; return }
        ModellWaehlen
        if (-not $script:Modell) { Info "Kein Modell gewählt. Später: .\setup.ps1 -Nur lokal"; return }
    }
    $m = $script:Modell
    if (OllamaHat $m) {
        Ok "Modell $m ist schon geladen"
    } else {
        if ($script:ModellPlatz -and -not (Frage "Der freie Speicherplatz reicht vielleicht nicht. Trotzdem laden?" "n")) {
            Info "Nicht geladen. Später: .\setup.ps1 -Nur lokal"
            return
        }
        Info "Lade $m (das kann eine Weile dauern) …"
        $code = Ausfuehren $script:Ollama @("pull", $m)
        if ($code -ne 0) {
            Warn "Download von $m fehlgeschlagen. Nochmal versuchen: .\setup.ps1 -Nur lokal (setzt fort, wo möglich)"
            return
        }
        Ok "Modell $m geladen"
    }
    if (KiSetzen "ollama.modell" $m) { Ok "Lokales Modell in config.toml: $m" }
}

# ---------------------------------------------------------------- Standard-KI
function StandardSetzen([string]$ki) {
    if ($ki -ne (StdAusConfig "config.toml")) {
        if (-not (KiSetzen "modell.standard" $ki)) { Warn "Standard-KI ließ sich nicht setzen."; return }
    }
    Ok "Standard-KI für neue Projekte: $(KiTitel $ki)"
}

function SchrittStandard {
    Titel "Standard-KI"
    AlleZustaende
    $jetzt = StdAusConfig "config.toml"
    $anzahl = @($script:Bereit).Count
    if ($Standard) {
        StandardSetzen $Standard
        if (-not (IstBereit $Standard)) { Warn "$(KiTitel $Standard) ist noch nicht bereit." }
    }
    if ($anzahl -eq 0) {
        Warn "Ohne KI kann gen_Ut nichts erzeugen. Später: im Tool oben auf eine KI klicken oder .\setup.ps1 -Nur gemini"
    }
    if ($Standard -or $anzahl -eq 0) { return }
    # vorhandene config.toml: die bisherige Standard-KI bleibt, solange sie bereit ist (FR-017)
    if (-not $ConfigNeu -and (IstBereit $jetzt)) {
        $vorschlag = $jetzt
        if ($Nur -or $anzahl -eq 1 -or -not $Interaktiv) { Ok "Standard-KI bleibt $(KiTitel $jetzt)"; return }
    } else {
        $d = JsonLesen (& $VenvPy -m genut ki standard-vorschlag --json 2>$null)
        $vorschlag = ""; if ($d) { $vorschlag = [string]$d.standard }
        if (-not $vorschlag) { $vorschlag = [string]$script:Bereit[0] }
        if ($AltVorschlag -and (IstBereit $AltVorschlag)) { $vorschlag = $AltVorschlag }
        if ($Nur) {
            $teil = KiName $Nur
            if (IstBereit $teil) { $vorschlag = $teil }
        }
        if ($ConfigNeu -and ($anzahl -eq 1 -or -not $Interaktiv)) { StandardSetzen $vorschlag; return }
        if (-not $ConfigNeu -and ($anzahl -eq 1 -or $Nur)) {
            if (Frage "Standard-KI auf $(KiTitel $vorschlag) umstellen? (bisher: $(KiTitel $jetzt), nicht bereit)") {
                StandardSetzen $vorschlag
            } else {
                Warn "Standard-KI bleibt $(KiTitel $jetzt) (nicht bereit). Umstellen: im Tool oben oder .\setup.ps1 -Standard ..."
            }
            return
        }
        if (-not $Interaktiv) {
            Warn "Standard-KI bleibt $(KiTitel $jetzt) (nicht bereit). Umstellen: im Tool oben oder .\setup.ps1 -Standard ..."
            return
        }
    }
    # mehrere bereit, mit Konsole: Auswahl mit Vorwahl
    Write-Host "Mehrere KIs sind bereit. Welche soll neue Projekte erzeugen? (im Tool jederzeit umschaltbar)"
    $reihe = @(); $vorwahl = 1
    foreach ($n in @("claude_code", "gemini", "ollama")) {
        if (IstBereit $n) {
            $reihe += $n
            if ($n -eq $vorschlag) { $vorwahl = $reihe.Count }
            $zusatz = ""; if ($n -eq $jetzt -and -not $ConfigNeu) { $zusatz = " (bisher)" }
            Write-Host "  $($reihe.Count)) $(KiTitel $n)$zusatz"
        }
    }
    $w = Read-Host "Auswahl [Enter = $vorwahl]"
    $w = "$w".Trim()
    if (-not $w) { $w = "$vorwahl" }
    $wahl = ""
    if ($w -match '^\d+$') {
        $k = [int]$w
        if ($k -ge 1 -and $k -le $reihe.Count) { $wahl = $reihe[$k - 1] }
    }
    if (-not $wahl) { Warn "Keine gültige Nummer – nehme $(KiTitel $vorschlag)."; $wahl = $vorschlag }
    StandardSetzen $wahl
}

function Zusammenfassung {
    $bereit = @(); $fehlt = @(); $problem = @()
    foreach ($z in $script:Zustaende) {
        $n = [string]$z.name
        if (-not $n) { continue }
        $t = KiTitel $n
        if ($n -eq "ollama") { $t = "$t (experimentell)" }
        if ($z.zustand -eq "bereit") { $bereit += $t }
        elseif ($z.zustand -eq "problem") { if ($z.ursache) { $problem += "$t – $($z.ursache)" } else { $problem += $t } }
        else { $fehlt += $t }
    }
    Write-Host ""
    if ($bereit.Count -gt 0) { Ok "bereit: $($bereit -join ', ')" } else { Warn "bereit: keine" }
    if ($fehlt.Count -gt 0) { Info "nicht eingerichtet: $($fehlt -join ', ')" }
    if ($problem.Count -gt 0) { Warn "Problem: $($problem -join ', ')" }
    if ($fehlt.Count -gt 0 -or $problem.Count -gt 0) {
        Info "Fehlende KIs kannst du später im Tool einrichten: oben im KI-Schalter auf die KI klicken."
    }
}

# ---------------------------------------------------------------- KI-Schritte
if ($KiDa) {
    if (-not $Nur -or $Nur -eq "claude") { SchrittClaude }
    if (-not $Nur -or $Nur -eq "gemini") { SchrittGemini }
    if (-not $Nur -or $Nur -eq "lokal") { SchrittLokal }
    SchrittStandard
} else {
    Titel "KI"
    Warn "Die KI-Einrichtung fehlt in dieser Version – Claude, Gemini und Lokal bitte selbst einrichten (siehe README)."
}

# ---------------------------------------------------------------- Startbefehl
# Pfad für "set PATH=…" in start.bat: cmd liest die Datei in der OEM-Codepage, deshalb bekannte Ordner als
# %VARIABLE% und nur ASCII; sonst $null (dann findet start.bat das Programm über den PATH des Benutzers).
function BatPfad([string]$pfad) {
    $rest = $pfad; $vorne = ""
    foreach ($v in @("LOCALAPPDATA", "APPDATA", "USERPROFILE", "ProgramFiles")) {
        $wert = [Environment]::GetEnvironmentVariable($v)
        if ($wert -and $pfad.StartsWith($wert.TrimEnd([char]92) + "\", [StringComparison]::OrdinalIgnoreCase)) {
            $vorne = "%$v%"; $rest = $pfad.Substring($wert.TrimEnd([char]92).Length)
            break
        }
    }
    if ($rest -match '[^\x20-\x7E]' -or $rest.Contains('"')) { return $null }
    return $vorne + $rest.Replace("%", "%%")
}

Titel "Startbefehl"
$pfadExtra = @()
if ($NodeDir -and $NodeDir -ne (Split-Path $NodeExe)) { $pfadExtra += $NodeDir }
$ollamaStart = $false
# nur wenn ein lokales Modell eingetragen ist (sonst braucht gen_Ut Ollama nicht)
if ((OllamaFinden) -and (KonfigModell)) {
    $ollamaStart = $true
    if ($pfadExtra -notcontains $OllamaDir) { $pfadExtra += $OllamaDir }
}
$batPfade = @()
foreach ($p in $pfadExtra) {
    $b = BatPfad $p
    if ($b) { $batPfade += $b } else { Warn "Ordner mit Sonderzeichen nicht in start.bat aufgenommen: $p" }
}
$start = @(
    '@echo off',
    'rem gen_Ut starten (angelegt von setup.ps1). Fenster offen lassen, beenden mit Strg+C.',
    'cd /d "%~dp0"',
    'set PYTHONUTF8=1'
)
if ($batPfade.Count -gt 0) { $start += 'set "PATH=' + ($batPfade -join ";") + ';%PATH%"' }
if ($ollamaStart) { $start += 'where ollama >nul 2>nul && (ollama list >nul 2>nul || (start "" /min ollama serve & ping -n 4 127.0.0.1 >nul))' }
$start += @(
    'for /f %%p in (''.venv\Scripts\python.exe -c "from genut.config import laden; print(laden()[''server''][''port''])"'') do set PORT=%%p',
    'start "" /b cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:%PORT%"',
    'echo gen_Ut laeuft auf http://127.0.0.1:%PORT% - Fenster offen lassen, beenden mit Strg+C',
    '.venv\Scripts\python.exe -m genut serve'
)
[IO.File]::WriteAllText((Join-Path $Wurzel "start.bat"), (($start -join "`r`n") + "`r`n"), $Utf8)
Ok "start.bat angelegt"

$lnkPfad = $null
try { $lnkPfad = Join-Path ([Environment]::GetFolderPath("Desktop")) "gen_Ut.lnk" } catch { $lnkPfad = $null }
if ($Interaktiv -and -not $Nur -and $lnkPfad -and -not (Test-Path -LiteralPath $lnkPfad) -and (Frage "Verknüpfung 'gen_Ut' auf dem Desktop anlegen?")) {
    try {
        $sh = New-Object -ComObject WScript.Shell
        $lnk = $sh.CreateShortcut($lnkPfad)
        $lnk.TargetPath = Join-Path $Wurzel "start.bat"
        $lnk.WorkingDirectory = $Wurzel
        $lnk.Save()
        Ok "Desktop-Verknüpfung angelegt"
    } catch {
        Warn "Desktop-Verknüpfung ließ sich nicht anlegen: $_"
    }
}

if ($KiDa) { Zusammenfassung }
Write-Host ""
Write-Host "Fertig! gen_Ut ist eingerichtet." -ForegroundColor Green
Write-Host "Starten: start.bat doppelklicken – dann öffnet sich gen_Ut im Browser."
Beenden 0
