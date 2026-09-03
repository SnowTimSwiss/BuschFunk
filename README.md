# BuschFunk

Einfache Software für simples Radio übers Internet.

Details siehe [`docs/buschfunk-spec.md`](docs/buschfunk-spec.md).

## Schnellstart (lokale Entwicklung, ohne echte Audio-Hardware)

```bash
python3 -m venv .venv
./.venv/bin/pip install -r backend/requirements.txt
cp .env.example .env
cd backend && AUDIO_BACKEND=dummy ../.venv/bin/python run.py
```

- Admin-UI: <http://localhost:8000/admin/> (Setup-Code steht im Terminal-Log)
- Hörer-Ansicht: <http://localhost:8000/listen/>
- API-Doku: <http://localhost:8000/docs>

Ohne `AUDIO_BACKEND=dummy` erkennt die App automatisch, ob ein PipeWire-
Server erreichbar ist, und fällt sonst selbst auf den Dummy-Modus zurück
(simulierte Busse/Pegel, kein echter Stream) - praktisch für Entwicklung
und Demos.

## Installation auf dem Pi (für den Betrieb im Lager)

Vorausgesetzt: Raspberry Pi OS Bookworm oder neuer, einmal mit Internet
verbunden (für die Paketinstallation), Mischpult per USB angeschlossen.

```bash
git clone https://github.com/SnowTimSwiss/BuschFunk.git
cd BuschFunk
./deploy/install.sh
```

Das Skript ist nicht-interaktiv und macht alles automatisch:

- installiert fehlende Pakete (`ffmpeg`, `pipewire`, `wireplumber`, `icecast2`)
- legt die Python-Umgebung an und installiert die App
- erzeugt eine `.env` mit zufälligem Session-Secret und Icecast-Passwort
- richtet Icecast passend dazu ein und startet es
- richtet BuschFunk als systemd-Dienst ein (startet automatisch bei jedem
  Neustart des Pi, auch nach Stromausfall)
- gibt am Ende direkt die Admin-URL und den einmaligen Setup-Code aus

Am Ende steht z.B.:

```
Admin-UI öffnen:   http://192.168.1.42:8000/admin/
Einmaliger Setup-Code fürs erste Login: 481203
```

Diese URL im Browser öffnen, Setup-Code eingeben, Admin-Passwort setzen -
fertig. Das Skript kann gefahrlos mehrfach laufen (z.B. nach einem Update),
bestehende `.env`/Passwörter werden nicht überschrieben.

Nur für externen Zugriff über eine eigene Domain zusätzlich nötig (optional):
[`deploy/cloudflared/config.yml.example`](deploy/cloudflared/config.yml.example)
einmalig einrichten (Anleitung steht in der Datei).

Für die echte PipeWire/Mischpult-Verkabelung: [`docs/audio-setup.md`](docs/audio-setup.md)
(auf echter Hardware noch zu verifizieren, siehe Spec Abschnitt 10).

Details zu den einzelnen Deploy-Dateien: [`deploy/systemd/buschfunk.service`](deploy/systemd/buschfunk.service),
[`deploy/icecast.xml.example`](deploy/icecast.xml.example).

## Struktur

```
backend/    FastAPI-App (Rundown/Live-Steuerung/Busse/Auth/Self-Update)
frontend/   Admin-UI (Regie) + Listener-UI, statisches Vanilla-JS
deploy/     systemd-Unit, Icecast-/cloudflared-Vorlagen, Install-Skript
docs/       Spezifikation + Audio-Setup-Notizen
```

## Lizenz

GPLv3, siehe [`LICENSE`](LICENSE)
