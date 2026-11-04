# gen_Ut – Einrichtung für Windows
#
#   setup.bat                                 (Doppelklick) fragt nach der Version und vor jeder Installation
#   powershell -ExecutionPolicy Bypass -File setup.ps1 -Version gemini
#   powershell -ExecutionPolicy Bypass -File setup.ps1 -Version claude -Ja
#
# Installiert nichts ohne Rückfrage. Python und Node.js landen bei Bedarf im Benutzer- bzw.
# Projektordner (keine Admin-Rechte nötig). Läuft mit Windows PowerShell 5.1 und PowerShell 7.
param(
    [ValidateSet("", "claude", "gemini", "lokal")]
    [string]$Version = "",
    [switch]$Ja
)

$ErrorActionPreference = "Continue"   # Fehler werden ausdrücklich geprüft (PS 5.1 bricht sonst bei stderr ab)
$ProgressPreference = "SilentlyContinue"   # Invoke-WebRequest ist sonst sehr langsam
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Set-Location -LiteralPath $PSScriptRoot
$Wurzel = (Get-Location).Path
$Utf8 = New-Object System.Text.UTF8Encoding($false)   # ohne BOM

function Titel($t) { Write-Host ""; Write-Host "== $t ==" -ForegroundColor White }
function Info($t)  { Write-Host "> $t" -ForegroundColor Cyan }
function Ok($t)    { Write-Host "OK $t" -ForegroundColor Green }
function Warn($t)  { Write-Host "!  $t" -ForegroundColor Yellow }
function Abbruch($t) {
    Write-Host "X  $t" -ForegroundColor Red
    if (-not $Ja) { Read-Host "Enter zum Schließen" | Out-Null }
    exit 1
}
function Frage($t) {
    if ($Ja) { return $true }
    $a = Read-Host "$t [J/n]"
    return -not ($a -match '^[nN]')
}
function Laden($url, $ziel) { Invoke-WebRequest -Uri $url -OutFile $ziel -UseBasicParsing -ErrorAction Stop }
function PfadNeuLaden {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}
function Befehl($name) { $c = Get-Command $name -ErrorAction SilentlyContinue; if ($c) { return $c.Source } return $null }

Write-Host "gen_Ut – Einrichtung (Windows)" -ForegroundColor White
New-Item -ItemType Directory -Force -Path ".werkzeuge" | Out-Null

# ---------------------------------------------------------------- Version
function StdAusConfig($datei) {
    if (-not (Test-Path $datei)) { return "" }
    $m = Select-String -Path $datei -Pattern '^standard\s*=\s*"([a-z_]+)"' | Select-Object -First 1
    if ($m) { return $m.Matches[0].Groups[1].Value } return ""
}
if (-not $Version -and (Test-Path "config.toml")) {
    switch (StdAusConfig "config.toml") { "claude_code" { $Version = "claude" } "gemini" { $Version = "gemini" } "ollama" { $Version = "lokal" } }
    if ($Version) { Info "Version aus config.toml: $Version" }
}
if (-not $Version) {
    if ($Ja) { Abbruch "Bitte die Version angeben: -Version claude|gemini|lokal" }
    Write-Host ""
    Write-Host "Welche Version willst du einrichten?"
    Write-Host "  1) Claude  - braucht ein Claude-Abo (Pro oder höher), beste Qualität"
    Write-Host "  2) Gemini  - gratis mit Google-Schlüssel (empfohlen, wenn du kein Claude-Abo hast)"
    Write-Host "  3) Lokal   - Ollama auf deinem Computer, nichts geht ins Internet (experimentell)"
    $w = Read-Host "Auswahl [2]"
    switch ($w) { "1" { $Version = "claude" } "3" { $Version = "lokal" } default { $Version = "gemini" } }
}
if (-not (Test-Path "versionen\$Version.toml")) { Abbruch "versionen\$Version.toml fehlt – ist das der gen_Ut-Ordner?" }

# ---------------------------------------------------------------- Python
Titel "Python"
$VenvPy = Join-Path $Wurzel ".venv\Scripts\python.exe"
$PyOk = "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
function VenvOk { if (-not (Test-Path $VenvPy)) { return $false }; & $VenvPy -c $PyOk 2>$null; return ($LASTEXITCODE -eq 0) }
function UvFinden {
    $u = Befehl "uv"; if ($u) { return $u }
    foreach ($k in @("$env:USERPROFILE\.local\bin\uv.exe", "$env:USERPROFILE\.cargo\bin\uv.exe")) { if (Test-Path $k) { return $k } }
    return $null
}

if (VenvOk) {
    Ok "Python-Umgebung .venv ist schon da ($(& $VenvPy --version))"
} else {
    if (Test-Path ".venv") { Remove-Item -Recurse -Force ".venv" }
    # 1. Python-Launcher „py“, 2. python.exe (nicht der Microsoft-Store-Platzhalter)
    $Py = $null
    foreach ($kandidat in @(@("py", "-3"), @("python"))) {
        $exe = Befehl $kandidat[0]
        if (-not $exe -or $exe -like "*WindowsApps*") { continue }
        $argumente = @(); if ($kandidat.Count -gt 1) { $argumente = $kandidat[1..($kandidat.Count - 1)] }
        & $exe @argumente -c $PyOk 2>$null
        if ($LASTEXITCODE -eq 0) { $Py = @($exe) + $argumente; break }
    }
    $angelegt = $false
    if ($Py) {
        $exe = $Py[0]; $argumente = @(); if ($Py.Count -gt 1) { $argumente = $Py[1..($Py.Count - 1)] }
        & $exe @argumente -m venv .venv 2>$null
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
            try { Invoke-RestMethod https://astral.sh/uv/install.ps1 -ErrorAction Stop | Invoke-Expression | Out-Null } catch { Abbruch "uv-Installation fehlgeschlagen: $_" }
            PfadNeuLaden
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

Info "Installiere die Python-Pakete (beim ersten Mal ein paar Minuten) …"
& $VenvPy -m pip install --disable-pip-version-check -e . *> ".werkzeuge\pip.log"
if ($LASTEXITCODE -ne 0) {
    Get-Content ".werkzeuge\pip.log" -Tail 25
    Abbruch "pip install ist fehlgeschlagen (ganzes Protokoll: .werkzeuge\pip.log)."
}
Ok "Python-Pakete installiert"

# ---------------------------------------------------------------- Node.js
Titel "Node.js"
$NodeExe = Join-Path $Wurzel ".werkzeuge\node\node.exe"
$NodeDir = $null
function NodeLaeuft($exe) { if (-not $exe -or -not (Test-Path $exe)) { return $false }; & $exe --version 2>$null | Out-Null; return ($LASTEXITCODE -eq 0) }
if (NodeLaeuft $NodeExe) {
    $NodeDir = Split-Path $NodeExe
} else {
    $sys = Befehl "node"
    $sysOk = $false
    if ($sys -and (Befehl "npm")) {
        & $sys -e "process.exit(+process.versions.node.split('.')[0] >= 20 ? 0 : 1)" 2>$null
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
        try { $index = Invoke-RestMethod https://nodejs.org/dist/index.json -ErrorAction Stop } catch { Abbruch "Keine Verbindung zu nodejs.org: $_" }
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
Info "Installiere die Node-Pakete (MathJax, Mermaid, sql.js) …"
$env:Path = "$NodeDir;$env:Path"
& (Join-Path $NodeDir "npm.cmd") ci --no-audit --no-fund --loglevel=error *> ".werkzeuge\npm.log"
if ($LASTEXITCODE -ne 0) {
    Get-Content ".werkzeuge\npm.log" -Tail 25
    Abbruch "npm ci ist fehlgeschlagen (Protokoll: .werkzeuge\npm.log)."
}
Ok "Node-Pakete installiert"

# ---------------------------------------------------------------- config.toml
Titel "Konfiguration"
if (-not (Test-Path "config.toml")) {
    Copy-Item "versionen\$Version.toml" "config.toml"
    Ok "config.toml für die Version '$Version' angelegt"
} elseif ((StdAusConfig "config.toml") -ne (StdAusConfig "versionen\$Version.toml")) {
    if (Frage "config.toml ist für eine andere Version eingestellt. Auf '$Version' umstellen (alte Datei -> config.toml.bak)?") {
        Copy-Item "config.toml" "config.toml.bak" -Force
        Copy-Item "versionen\$Version.toml" "config.toml" -Force
        Ok "config.toml umgestellt"
    } else { Warn "config.toml bleibt unverändert" }
} else {
    Ok "config.toml passt schon"
}

# ---------------------------------------------------------------- KI einrichten
function ClaudeFinden {
    $c = Befehl "claude"; if ($c) { return $c }
    $k = "$env:USERPROFILE\.local\bin\claude.exe"; if (Test-Path $k) { return $k }
    return $null
}
function SchluesselOk {
    & $VenvPy -c "from genut.modelle.gemini import Gemini; Gemini({'modell': ''})._kandidaten()" 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}
function SchluesselSpeichern($key) {
    $zeilen = @()
    if (Test-Path ".env") { $zeilen = @(Get-Content ".env" | Where-Object { $_ -notmatch "GEMINI_API_KEY" }) }
    $zeilen += "GEMINI_API_KEY=$key"
    [IO.File]::WriteAllText((Join-Path $Wurzel ".env"), (($zeilen -join "`n") + "`n"), $Utf8)
}
function SchluesselLesen {
    $s = Read-Host "Schlüssel einfügen (wird nicht angezeigt)" -AsSecureString
    $b = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)
    try { return ([Runtime.InteropServices.Marshal]::PtrToStringBSTR($b)).Trim() } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b) }
}

switch ($Version) {
"claude" {
    Titel "Claude"
    if (-not (Befehl "git")) {
        Warn "Claude Code braucht unter Windows 'Git for Windows'."
        if ((Befehl "winget") -and (Frage "Git for Windows mit winget installieren?")) {
            winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements
            PfadNeuLaden
        } else { Warn "Bitte Git von https://git-scm.com/download/win installieren." }
    }
    $cl = ClaudeFinden
    if (-not $cl -and (Frage "Die Claude-Code-CLI fehlt. Jetzt installieren (offizieller Installer von claude.ai)?")) {
        try { Invoke-RestMethod https://claude.ai/install.ps1 -ErrorAction Stop | Invoke-Expression } catch { Warn "Installation fehlgeschlagen: $_" }
        PfadNeuLaden
        $cl = ClaudeFinden
    }
    if ($cl) {
        Ok "Claude Code gefunden: $cl"
        if (-not (Befehl "claude")) {
            $t = [IO.File]::ReadAllText((Join-Path $Wurzel "config.toml"))
            $t = $t -replace '(?m)^befehl = "claude"', ('befehl = "' + ($cl -replace '\\', '/') + '"')
            [IO.File]::WriteAllText((Join-Path $Wurzel "config.toml"), $t, $Utf8)
        }
        Warn "Melde dich einmal mit deinem Claude-Konto an (Pro oder höher): '$cl' starten, anmelden, mit /exit beenden."
        if (-not $Ja -and (Frage "Claude jetzt zum Anmelden starten?")) { & $cl }
    } else {
        Warn "Ohne Claude Code funktioniert diese Version nicht. Anleitung: https://claude.com/claude-code"
    }
}
"gemini" {
    Titel "Gemini"
    $hat = (Test-Path ".env") -and (Select-String -Path ".env" -Pattern '^\s*GEMINI_API_KEY\s*=\s*\S' -Quiet)
    if ($hat) {
        Ok "Gemini-Schlüssel steht schon in .env"
    } else {
        $key = $env:GEMINI_API_KEY
        if (-not $key -and -not $Ja) {
            Write-Host "Du brauchst einen kostenlosen Schlüssel von Google AI Studio:"
            Write-Host "  1. https://aistudio.google.com/apikey öffnen und mit einem Google-Konto anmelden"
            Write-Host "  2. 'Create API key' klicken und den Schlüssel kopieren"
            if (Frage "Seite jetzt im Browser öffnen?") { Start-Process "https://aistudio.google.com/apikey" }
            $key = SchluesselLesen
        }
        if ($key) { SchluesselSpeichern $key.Trim(); Ok "Schlüssel in .env gespeichert (nur auf diesem Computer)" }
        else { Warn "Kein Schlüssel eingegeben. Später nachtragen: Datei .env mit der Zeile GEMINI_API_KEY=... anlegen." }
    }
    if ((Test-Path ".env") -and (Select-String -Path ".env" -Pattern "GEMINI_API_KEY" -Quiet)) {
        if (SchluesselOk) { Ok "Schlüssel funktioniert" }
        else {
            Warn "Schlüssel wurde nicht akzeptiert (oder keine Internetverbindung)."
            if (-not $Ja -and (Frage "Schlüssel neu eingeben?")) {
                $key = SchluesselLesen
                if ($key) {
                    SchluesselSpeichern $key
                    if (SchluesselOk) { Ok "Schlüssel funktioniert" } else { Warn "Auch dieser Schlüssel geht nicht – prüfe ihn auf aistudio.google.com." }
                }
            } else { Warn "Prüfe die Zeile GEMINI_API_KEY=... in der Datei .env." }
        }
    }
}
"lokal" {
    Titel "Lokal (Ollama) – experimentell"
    Warn "Die lokale Version ist experimentell: langsamer und einfacher als Claude oder Gemini."
    $ramGb = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
    if ($ramGb -lt 15) { Warn "Dein Computer hat $ramGb GB RAM – empfohlen sind 16 GB. Es kann sehr langsam werden." }
    $ol = Befehl "ollama"
    if (-not $ol) {
        if ((Befehl "winget") -and (Frage "Ollama mit winget installieren?")) {
            winget install --id Ollama.Ollama -e --source winget --accept-package-agreements --accept-source-agreements
            PfadNeuLaden
            $ol = Befehl "ollama"
            if (-not $ol -and (Test-Path "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe")) { $ol = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" }
        }
        if (-not $ol) {
            Start-Process "https://ollama.com/download"
            Abbruch "Bitte Ollama von https://ollama.com/download installieren und das Setup neu starten."
        }
    }
    & $ol list 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { Info "Starte Ollama …"; Start-Process -WindowStyle Hidden $ol "serve"; Start-Sleep 4 }
    $modell = (& $VenvPy -c "from genut.config import laden; print(laden()['ollama']['modell'])").Trim()
    $vorhanden = (& $ol list 2>$null | ForEach-Object { ($_ -split '\s+')[0] }) -contains $modell
    if ($vorhanden) { Ok "Modell $modell ist schon da" }
    elseif (Frage "Modell $modell herunterladen (ca. 3 GB)?") { & $ol pull $modell; Ok "Modell $modell geladen" }
    else { Warn "Ohne Modell geht es nicht: später 'ollama pull $modell' ausführen." }
}
}

# ---------------------------------------------------------------- Startbefehl
Titel "Startbefehl"
$start = @(
    '@echo off',
    'rem gen_Ut starten (angelegt von setup.ps1). Fenster offen lassen, beenden mit Strg+C.',
    'cd /d "%~dp0"'
)
if ($Version -eq "lokal") { $start += 'where ollama >nul 2>nul && (ollama list >nul 2>nul || start "" /min ollama serve)' }
$start += @(
    'for /f %%p in (''.venv\Scripts\python.exe -c "from genut.config import laden; print(laden()[''server''][''port''])"'') do set PORT=%%p',
    'start "" /b cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:%PORT%"',
    'echo gen_Ut laeuft auf http://127.0.0.1:%PORT% - Fenster offen lassen, beenden mit Strg+C',
    '.venv\Scripts\python.exe -m genut serve'
)
[IO.File]::WriteAllText((Join-Path $Wurzel "start.bat"), (($start -join "`r`n") + "`r`n"), $Utf8)
Ok "start.bat angelegt"

if (-not $Ja -and (Frage "Verknüpfung 'gen_Ut' auf dem Desktop anlegen?")) {
    $sh = New-Object -ComObject WScript.Shell
    $lnk = $sh.CreateShortcut((Join-Path ([Environment]::GetFolderPath("Desktop")) "gen_Ut.lnk"))
    $lnk.TargetPath = Join-Path $Wurzel "start.bat"
    $lnk.WorkingDirectory = $Wurzel
    $lnk.Save()
    Ok "Desktop-Verknüpfung angelegt"
}

Write-Host ""
Write-Host "Fertig! gen_Ut ist eingerichtet (Version: $Version)." -ForegroundColor Green
Write-Host "Starten: start.bat doppelklicken – dann öffnet sich http://127.0.0.1:8765 im Browser."
if (-not $Ja) { Read-Host "Enter zum Schließen" | Out-Null }
