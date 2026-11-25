@echo off
rem gen_Ut - Einrichtung fuer Windows: einfach doppelklicken.
rem Startet setup.ps1 ohne die PowerShell-Ausfuehrungsrichtlinie dauerhaft zu aendern.
rem Schalter werden weitergereicht: setup.bat -Nur lokal, setup.bat -Standard gemini (auch --nur lokal).
rem Alle Schalter: setup.bat -Hilfe
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
