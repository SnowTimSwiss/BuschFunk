#!/usr/bin/env bash
# Erstinstallation auf dem Raspberry Pi (Raspberry Pi OS Bookworm o. neuer,
# PipeWire+WirePlumber als Audio-System vorausgesetzt). Nicht destruktiv -
# kann mehrfach laufen (überschreibt keine vorhandene .env). Installiert
# fehlende Pakete automatisch, richtet Icecast mit einem generierten
# Passwort ein, fragt optional den Cloudflare Tunnel ab und startet den
# Dienst - danach nur noch die Admin-UI öffnen und den ausgegebenen
# Setup-Code eintippen.
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

# 6. Cloudflare Tunnel (optional, externer Zugriff über eigene Domain) -----
EXTERNAL_URL=""

setup_cloudflare_tunnel() {
  echo ""
  echo "== Cloudflare Tunnel einrichten =="

  if ! command -v cloudflared >/dev/null; then
    echo "-- lade cloudflared herunter --"
    local arch cf_arch
    arch=$(dpkg --print-architecture 2>/dev/null || uname -m)
    case "$arch" in
      arm64|aarch64) cf_arch=arm64 ;;
      armhf|armv7l|armv6l) cf_arch=arm ;;
      amd64|x86_64) cf_arch=amd64 ;;
      *) cf_arch="" ;;
    esac
    if [ -z "$cf_arch" ]; then
      echo "WARNUNG: Architektur '$arch' nicht erkannt - cloudflared bitte manuell installieren (https://github.com/cloudflare/cloudflared/releases)"
      return 1
    fi
    sudo curl -fsSL -o /usr/local/bin/cloudflared \
      "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-$cf_arch" \
      || { echo "WARNUNG: Download von cloudflared fehlgeschlagen"; return 1; }
    sudo chmod +x /usr/local/bin/cloudflared
  fi

  if [ ! -f "$HOME/.cloudflared/cert.pem" ]; then
    echo ""
    echo "-- Cloudflare-Login nötig: den jetzt angezeigten Link auf einem Gerät mit Browser öffnen und die Domain auswählen --"
    cloudflared tunnel login || { echo "WARNUNG: Login fehlgeschlagen oder abgebrochen"; return 1; }
    [ -f "$HOME/.cloudflared/cert.pem" ] || { echo "WARNUNG: Login nicht abgeschlossen"; return 1; }
  fi

  local tunnel_name tunnel_domain
  read -rp "Name für den Tunnel [buschfunk]: " tunnel_name
  tunnel_name="${tunnel_name:-buschfunk}"
  read -rp "Domain, unter der BuschFunk erreichbar sein soll (z.B. buschfunk.deine-domain.tld): " tunnel_domain
  if [ -z "$tunnel_domain" ]; then
    echo "-- keine Domain angegeben, Tunnel-Einrichtung übersprungen --"
    return 1
  fi

  if ! cloudflared tunnel list 2>/dev/null | awk '{print $2}' | grep -qx "$tunnel_name"; then
    cloudflared tunnel create "$tunnel_name" \
      || { echo "WARNUNG: Tunnel konnte nicht angelegt werden"; return 1; }
  fi

  cloudflared tunnel route dns "$tunnel_name" "$tunnel_domain" \
    || { echo "WARNUNG: DNS-Route konnte nicht angelegt werden (Domain evtl. nicht in diesem Cloudflare-Account)"; return 1; }

  local tunnel_id cred_file
  tunnel_id=$(cloudflared tunnel list 2>/dev/null | awk -v n="$tunnel_name" '$2==n{print $1}')
  cred_file="$HOME/.cloudflared/$tunnel_id.json"
  [ -f "$cred_file" ] || { echo "WARNUNG: Credentials-Datei ($cred_file) nicht gefunden"; return 1; }

  sudo mkdir -p /etc/cloudflared
  sudo cp "$HOME/.cloudflared/cert.pem" /etc/cloudflared/cert.pem
  sudo cp "$cred_file" "/etc/cloudflared/$tunnel_id.json"
  sed \
    -e "s#^tunnel: .*#tunnel: $tunnel_name#" \
    -e "s#^credentials-file: .*#credentials-file: /etc/cloudflared/$tunnel_id.json#" \
    -e "s#hostname: buschfunk.deine-domain.tld#hostname: $tunnel_domain#" \
    deploy/cloudflared/config.yml.example | sudo tee /etc/cloudflared/config.yml > /dev/null

  sudo cloudflared service install || echo "HINWEIS: 'cloudflared service install' evtl. schon vorher eingerichtet - ignoriere"
  sudo systemctl enable --now cloudflared \
    || { echo "WARNUNG: cloudflared-Dienst konnte nicht gestartet werden"; return 1; }

  EXTERNAL_URL="https://$tunnel_domain"
  echo "-- Cloudflare Tunnel eingerichtet: $EXTERNAL_URL --"
}

if [ -t 0 ]; then
  read -rp "Cloudflare Tunnel für externen Zugriff einrichten (eigene Domain im Cloudflare-Account nötig)? [y/N] " SETUP_TUNNEL
  case "$SETUP_TUNNEL" in
    [JjYy]*)
      setup_cloudflare_tunnel || echo "-- Cloudflare Tunnel übersprungen/fehlgeschlagen, kann später manuell eingerichtet werden (siehe deploy/cloudflared/config.yml.example) --"
      ;;
    *) ;;
  esac
else
  echo "HINWEIS: kein interaktives Terminal erkannt - Cloudflare-Tunnel-Einrichtung übersprungen (später manuell möglich, siehe deploy/cloudflared/config.yml.example)"
fi

# 7. Admin-URL + Setup-Code direkt anzeigen --------------------------------
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
echo " Admin-UI (lokal):   http://$IP:8000/admin/"
echo " Hörer-Ansicht:       http://$IP:8000/listen/"
if [ -n "$EXTERNAL_URL" ]; then
  echo " Admin-UI (extern):  $EXTERNAL_URL/admin/"
  echo " Hörer-Ansicht (extern): $EXTERNAL_URL/listen/"
fi
if [ -n "$CODE" ]; then
  echo ""
  echo " Einmaliger Setup-Code fürs erste Login: $CODE"
else
  echo ""
  echo " Setup-Code steht im Log (noch nicht gefunden, ggf. kurz warten):"
  echo "   journalctl --user -u buschfunk.service -f"
fi
echo "======================================================"
if [ -z "$EXTERNAL_URL" ]; then
  echo ""
  echo "Für externen Zugriff über eine eigene Domain kann dieses Skript erneut"
  echo "gestartet werden (fragt dann wieder nach dem Cloudflare Tunnel), oder"
  echo "manuell: siehe deploy/cloudflared/config.yml.example"
fi
