#!/usr/bin/env bash
# Erstinstallation auf dem Raspberry Pi (Raspberry Pi OS Bookworm o. neuer,
# PipeWire+WirePlumber als Audio-System vorausgesetzt). Nicht destruktiv -
# fragt vor allem Kritischen nach, kann mehrfach laufen.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

echo "== BuschFunk Setup =="
echo "Repo: $REPO_DIR"

command -v python3 >/dev/null || { echo "python3 fehlt"; exit 1; }
command -v ffmpeg >/dev/null || echo "WARNUNG: ffmpeg nicht gefunden - 'sudo apt install ffmpeg'"
command -v pw-dump >/dev/null || echo "WARNUNG: PipeWire (pw-dump) nicht gefunden - läuft dann im Dummy-Audio-Modus"
command -v wpctl >/dev/null || echo "WARNUNG: wpctl (wireplumber) nicht gefunden - Mute/Unmute funktioniert dann nicht"
command -v icecast2 >/dev/null || echo "HINWEIS: Icecast2 nicht gefunden - 'sudo apt install icecast2', danach deploy/icecast.xml.example einrichten"
command -v cloudflared >/dev/null || echo "HINWEIS: cloudflared nicht gefunden, siehe https://github.com/cloudflare/cloudflared - nur für externen Zugriff nötig"

if [ ! -d .venv ]; then
  echo "-- lege Python-venv an --"
  python3 -m venv .venv
fi
./.venv/bin/pip install -q --upgrade pip
./.venv/bin/pip install -q -r backend/requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
  sed -i "s/^SESSION_SECRET=.*/SESSION_SECRET=$SECRET/" .env
  echo "-- .env angelegt mit zufälligem SESSION_SECRET - ICECAST_SOURCE_PASSWORD noch anpassen! --"
fi

mkdir -p media

echo ""
echo "== systemd User-Service einrichten =="
mkdir -p "$HOME/.config/systemd/user"
sed "s#%h#$HOME#g" deploy/systemd/buschfunk.service > "$HOME/.config/systemd/user/buschfunk.service"
loginctl enable-linger "$USER" || echo "WARNUNG: 'loginctl enable-linger' fehlgeschlagen - Service startet dann nur bei aktiver Login-Session"
systemctl --user daemon-reload
systemctl --user enable buschfunk.service

echo ""
echo "Fertig. Nächste Schritte:"
echo "  1. .env prüfen/anpassen (ICECAST_SOURCE_PASSWORD etc.)"
echo "  2. Icecast einrichten: deploy/icecast.xml.example -> /etc/icecast2/icecast.xml, dann 'sudo systemctl restart icecast2'"
echo "  3. (optional, für externen Zugriff) cloudflared einrichten: deploy/cloudflared/config.yml.example -> ~/.cloudflared/config.yml"
echo "  4. Dienst starten: systemctl --user start buschfunk.service"
echo "  5. Setup-Code im Log holen: journalctl --user -u buschfunk.service -f"
echo "  6. Admin-UI öffnen: http://<pi-ip>:8000/admin/"
