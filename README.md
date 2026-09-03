# BuschFunk

Einfache Software für simples Radio übers Internet.

Lagerradio-Software für das Regiolager 27: läuft auf einem Raspberry Pi,
streamt lokal per WLAN und öffentlich per Cloudflare Tunnel, wird über eine
Web-Admin-UI bedient. Details siehe [`docs/buschfunk-spec.md`](docs/buschfunk-spec.md).

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

## Deployment auf dem Pi

Siehe [`deploy/install.sh`](deploy/install.sh) sowie
[`deploy/systemd/buschfunk.service`](deploy/systemd/buschfunk.service),
[`deploy/icecast.xml.example`](deploy/icecast.xml.example) und
[`deploy/cloudflared/config.yml.example`](deploy/cloudflared/config.yml.example).
Für die echte PipeWire/Mischpult-Verkabelung: [`docs/audio-setup.md`](docs/audio-setup.md)
(auf echter Hardware noch zu verifizieren, siehe Spec Abschnitt 10).

## Struktur

```
backend/    FastAPI-App (Rundown/Live-Steuerung/Busse/Auth/Self-Update)
frontend/   Admin-UI (Regie) + Listener-UI, statisches Vanilla-JS
deploy/     systemd-Unit, Icecast-/cloudflared-Vorlagen, Install-Skript
docs/       Spezifikation + Audio-Setup-Notizen
```

## Lizenz

GPLv3, siehe [`LICENSE`](LICENSE)