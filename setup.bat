@echo off
rem gen_Ut - Einrichtung fuer Windows: einfach doppelklicken.
rem Startet setup.ps1 ohne die PowerShell-Ausfuehrungsrichtlinie dauerhaft zu aendern.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
