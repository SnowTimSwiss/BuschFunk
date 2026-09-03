#!/usr/bin/env bash
# Erstinstallation auf dem Raspberry Pi (Raspberry Pi OS Bookworm o. neuer,
# PipeWire+WirePlumber als Audio-System vorausgesetzt). Nicht destruktiv -
# kann mehrfach laufen (überschreibt keine vorhandene .env). Installiert
# fehlende Pakete automatisch, richtet Icecast mit einem generierten
# Passwort ein und startet den Dienst - danach nur noch die Admin-UI öffnen
# und den ausgegebenen Setup-Code eintippen.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

echo "== BuschFunk Setup =="
echo "Repo: $REPO_DIR"
echo ""

# 1. Fehlende System-Pakete automatisch installieren -----------------------
NEEDED_PKGS=()
command -v python3 >/dev/null || NEEDED_PKGS+=(python3 python3-venv)
command -v ffmpeg >/dev/null || NEEDED_PKGS+=(ffmpeg)
command -v pw-dump >/dev/null || NEEDED_PKGS+=(pipewire pipewire-audio-client-libraries)
command -v wpctl >/dev/null || NEEDED_PKGS+=(wireplumber)
command -v icecast2 >/dev/null || NEEDED_PKGS+=(icecast2)

if [ ${#NEEDED_PKGS[@]} -gt 0 ]; then
  if command -v apt-get >/dev/null; then
    echo "-- installiere fehlende Pakete: ${NEEDED_PKGS[*]} --"
    sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "${NEEDED_PKGS[@]}"
  else
    echo "WARNUNG: apt-get nicht gefunden - bitte manuell installieren: ${NEEDED_PKGS[*]}"
  fi
fi

command -v cloudflared >/dev/null || echo "HINWEIS: cloudflared nicht gefunden, siehe https://github.com/cloudflare/cloudflared - nur für externen Zugriff nötig, optional"

# 2. Python-venv + Abhängigkeiten -------------------------------------------
if [ ! -d .venv ]; then
  echo "-- lege Python-venv an --"
  python3 -m venv .venv
fi
./.venv/bin/pip install -q --upgrade pip
./.venv/bin/pip install -q -r backend/requirements.txt

# 3. .env mit zufälligen Secrets anlegen (nur beim allerersten Lauf) -------
if [ ! -f .env ]; then
  cp .env.example .env
  SESSION_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
  ICECAST_SOURCE_PW=$(python3 -c "import secrets; print(secrets.token_urlsafe(16))")
  sed -i "s/^SESSION_SECRET=.*/SESSION_SECRET=$SESSION_SECRET/" .env
  sed -i "s/^ICECAST_SOURCE_PASSWORD=.*/ICECAST_SOURCE_PASSWORD=$ICECAST_SOURCE_PW/" .env
  echo "-- .env angelegt mit zufälligem SESSION_SECRET und Icecast-Passwort --"
fi

mkdir -p media

# 4. Icecast automatisch konfigurieren (Passwort aus .env übernehmen) ------
if command -v icecast2 >/dev/null && [ -d /etc/icecast2 ]; then
  ICECAST_SOURCE_PW=$(grep '^ICECAST_SOURCE_PASSWORD=' .env | cut -d= -f2-)
  RELAY_PW=$(python3 -c "import secrets; print(secrets.token_urlsafe(16))")
  ADMIN_PW=$(python3 -c "import secrets; print(secrets.token_urlsafe(16))")
  echo "-- konfiguriere Icecast (/etc/icecast2/icecast.xml) --"
  sed \
    -e "s/CHANGE-ME-icecast-source-password/$ICECAST_SOURCE_PW/" \
    -e "s/CHANGE-ME-icecast-relay-password/$RELAY_PW/" \
    -e "s/CHANGE-ME-icecast-admin-password/$ADMIN_PW/" \
    deploy/icecast.xml.example | sudo tee /etc/icecast2/icecast.xml > /dev/null
  # Debian-Paket startet Icecast nur, wenn es explizit aktiviert ist:
  if [ -f /etc/default/icecast2 ]; then
    sudo sed -i 's/^ENABLE=false/ENABLE=true/' /etc/default/icecast2
  fi
  sudo systemctl enable --now icecast2 2>/dev/null || sudo systemctl restart icecast2
else
  echo "WARNUNG: Icecast2 nicht gefunden/eingerichtet - der Stream funktioniert erst nach manuellem Setup, siehe deploy/icecast.xml.example"
fi

# 5. BuschFunk als systemd User-Service einrichten und starten -------------
echo ""
echo "== systemd User-Service einrichten =="
mkdir -p "$HOME/.config/systemd/user"
sed "s#%h#$HOME#g" deploy/systemd/buschfunk.service > "$HOME/.config/systemd/user/buschfunk.service"
loginctl enable-linger "$USER" || echo "WARNUNG: 'loginctl enable-linger' fehlgeschlagen - Service startet dann nur bei aktiver Login-Session"
systemctl --user daemon-reload
systemctl --user enable --now buschfunk.service
systemctl --user restart buschfunk.service

# 6. Admin-URL + Setup-Code direkt anzeigen --------------------------------
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
[ -z "$IP" ] && IP="<pi-ip>"

echo ""
echo "-- warte auf Serverstart --"
CODE=""
for _ in $(seq 1 15); do
  sleep 1
  CODE=$(journalctl --user -u buschfunk.service --no-pager 2>/dev/null \
    | grep -A1 "BuschFunk Setup-Code" | grep -oE '[0-9]{6}' | tail -1 || true)
  [ -n "$CODE" ] && break
done

echo ""
echo "======================================================"
echo " Fertig! BuschFunk läuft."
echo ""
echo " Admin-UI öffnen:   http://$IP:8000/admin/"
echo " Hörer-Ansicht:      http://$IP:8000/listen/"
if [ -n "$CODE" ]; then
  echo ""
  echo " Einmaliger Setup-Code fürs erste Login: $CODE"
else
  echo ""
  echo " Setup-Code steht im Log (noch nicht gefunden, ggf. kurz warten):"
  echo "   journalctl --user -u buschfunk.service -f"
fi
echo "======================================================"
echo ""
echo "Optional, nur für externen Zugriff über eine eigene Domain:"
echo "  cloudflared einrichten, siehe deploy/cloudflared/config.yml.example"
