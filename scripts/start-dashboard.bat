@echo off
rem Uruchamia dashboard w WSL w zminimalizowanym oknie.
rem Autostart: Win+R -> shell:startup -> wklej tam skrot do tego pliku.
rem
rem Ustaw ponizej nazwe dystrybucji WSL (wsl -l -v) i sciezke repozytorium w WSL.
set "WSL_DISTRO=Ubuntu"
set "REPO_DIR=~/code/scripts/app-working-check"

start "App Dashboard" /min wsl.exe -d %WSL_DISTRO% -- bash -lc "%REPO_DIR%/scripts/start-dashboard.sh"
