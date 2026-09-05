# BuschFunk

Einfache Software für simples Radio übers Internet.

Musik und Jingles aus der eigenen Mediathek, ein Mischpult mit Pegeln und
Lautstärkereglern, ein grosser "Auf Sendung"-Schalter - mehr braucht ein
Lagerradio nicht. Details siehe [`docs/buschfunk-spec.md`](docs/buschfunk-spec.md).

## Was die Regie kann

- **Mediathek:** MP3s per Drag-and-Drop hochladen, umbenennen, sofort abspielen
  oder an die Warteschlange hängen.
- **Playlists:** anlegen, füllen, umsortieren, der Reihe nach oder zufällig
  starten. Mit "endlos wiederholen" geht die Musik nie von selbst aus.
- **Jingles:** ein Titel mit ★ wird zum Knopf im Jingle-Board und läuft auf
  Knopfdruck *über* die Musik, ohne sie zu stoppen.
- **Aussenreporter:** in den Einstellungen einen QR-Code erzeugen, mit dem
  Handy scannen und das Handy als eigenen, zunächst stummen Mikrofonkanal
  verbinden. Der Reporter kann sich selbst live/stumm schalten; die Regie kann
  ihn jederzeit trennen.
- **Mischpult:** nur wirklich angeschlossene Geräte, je mit Live-Pegel,
  Lautstärkeregler (Eingänge bis 300%), Stumm-Schalter und bei Eingängen einem
  Kanal-Modus (Stereo/Mono/Nur links/Nur rechts) für Quellen, die nicht sauber
  Stereo liefern, dazu ein Master-Meter.
- **Auf Sendung:** ein Schalter gibt den gemeinsamen Master-Ausgang frei;
  off air stoppt nur diese Ausgabe. Einzelne Geräte und der Player bleiben
  unverändert.
- **Limiter:** der Stream selbst hat einen Deckel bei 95% - schützt vor hartem
  Verzerren, wenn am Pult mal jemand zu heiss reingeht.

## Schnellstart (lokale Entwicklung, ohne echte Audio-Hardware)

```bash
python3 -m venv .venv
./.venv/bin/pip install -r backend/requirements.txt
cp .env.example .env
cd backend && AUDIO_BACKEND=demo ../.venv/bin/python run.py
```

- Admin-UI: <http://localhost:8000/admin/> (Setup-Code steht im Terminal-Log)
  – solange noch kein Admin-Passwort gesetzt ist
- Hörer-Ansicht: <http://localhost:8000/listen/>
- API-Doku: <http://localhost:8000/docs>

`AUDIO_BACKEND` steuert, woher der Ton kommt:

- `auto` (Standard): PipeWire, falls erreichbar - sonst gar keine Geräte.
- `pipewire` / `dummy`: das jeweilige Backend erzwingen.
- `demo`: simulierte Geräte und Pegel für Entwicklung und Screenshots.

Wichtig: ausserhalb von `demo` zeigt die Admin-UI **nur Geräte, die wirklich
am Rechner hängen**. Wenn dort nichts steht, hängt auch nichts dran.

Der Aussenreporter braucht für den Mikrofonzugriff HTTPS (oder `localhost`).
Für den später eingerichteten Cloudflare-Tunnel ist das automatisch gegeben;
über eine reine `http://<Pi-IP>:8000`-Adresse lässt sich die Reporter-Seite
öffnen, aber noch kein Mikrofon freigeben.

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
- fragt interaktiv, ob ein Cloudflare Tunnel für externen Zugriff über eine
  eigene Domain eingerichtet werden soll, und führt bei Bedarf komplett
  durch (Login, Tunnel anlegen, DNS-Route, systemd-Dienst) - kann bei "Nein"
  jederzeit übersprungen und später durch erneutes Ausführen nachgeholt werden
- richtet BuschFunk als systemd-Dienst ein (startet automatisch bei jedem
  Neustart des Pi, auch nach Stromausfall)
- gibt am Ende direkt die Admin-URL(s) und den einmaligen Setup-Code aus

Am Ende steht z.B.:

```
Admin-UI öffnen:   http://192.168.1.42:8000/admin/
Einmaliger Setup-Code fürs erste Login: 481203
```

Diese URL im Browser öffnen, Setup-Code eingeben, Admin-Passwort setzen -
fertig. Das Skript kann gefahrlos mehrfach laufen (z.B. nach einem Update),
bestehende `.env`/Passwörter werden nicht überschrieben.

Voraussetzung für den Cloudflare Tunnel: eine Domain, die im eigenen
Cloudflare-Account verwaltet wird. Ohne das läuft BuschFunk trotzdem -
dann nur lokal im Lager-WLAN erreichbar. Details/manuelles Setup:
[`deploy/cloudflared/config.yml.example`](deploy/cloudflared/config.yml.example).

Für die echte PipeWire/Mischpult-Verkabelung: [`docs/audio-setup.md`](docs/audio-setup.md)
(auf echter Hardware noch zu verifizieren, siehe Spec Abschnitt 11).

Details zu den einzelnen Deploy-Dateien: [`deploy/systemd/buschfunk.service`](deploy/systemd/buschfunk.service),
[`deploy/icecast.xml.example`](deploy/icecast.xml.example).

## Struktur

```
backend/    FastAPI-App (Mediathek/Playlists/Player/Mischpult/Auth/Self-Update)
frontend/   Admin-UI (Regie) + Listener-UI, statisches Vanilla-JS
deploy/     systemd-Unit, Icecast-/cloudflared-Vorlagen, Install-Skript
docs/       Spezifikation + Audio-Setup-Notizen
```

## Lizenz

GPLv3, siehe [`LICENSE`](LICENSE)
