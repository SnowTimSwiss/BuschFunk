# BuschFunk – technische Spezifikation

Lagerradio für das Regiolager 27. Läuft auf einem Raspberry Pi (oder beliebigem Linux-Rechner) vor Ort, streamt lokal per WLAN und öffentlich per Cloudflare Tunnel, wird über eine Web-Admin-UI bedient. Lizenz: **GPLv3** (AGPLv3 falls je eine gehostete/SaaS-Variante entsteht).

## 1. Rahmenbedingungen

- Lagerplatz ca. 2 Hektar, Turm/Mast 5–10 m Höhe für Antenne/Outdoor-AP verfügbar.
- Strom: entweder Netzstrom vor Ort, sonst Jackery + Solarpanel. Geschätzte Dauerlast der Technik: ~20–35 W (Pi, USB-Audiointerface, Outdoor-AP, ggf. 4G-Router).
- Sendebetrieb: ca. 1–2 h Live-Sendung pro Tag, restliche Zeit Playlist/Dauerbetrieb möglich.
- Erwartete Hörerzahl: max. ca. 50, gleichzeitig über WLAN vor Ort und mobil/extern.
- Bestehendes Equipment: analoges Mischpult, diverse Mikrofone aus dem Bandraum (u.a. Shure Beta 58 – supercardioid, für Live-Vocals/Instrumente geeignet, für Interviews eher ein Mikro mit breiterer Charakteristik verwenden). Spotify-Wiedergabe läuft über einen Laptop, der analog/per USB direkt am Mischpult angeschlossen wird (kein spotifyd/librespot nötig).

## 2. Architektur-Überblick

**Kernidee des Audio-Signalwegs:** Alle Quellen (Mischpult, weitere USB-Audiogeräte, ein interner "Player" für Jingles/Intros/Outros/Playlist-Dateien) speisen dauerhaft in einen ALSA/PipeWire-Loopback-Bus ein, jede Quelle einzeln stumm-/lautschaltbar. Genau **ein** ffmpeg-Prozess liest diesen Loopback dauerhaft aus und streamt an Icecast – dadurch ist "live/nicht live"-Umschalten nur Mute/Unmute im Hintergrund, nie ein Stream-Reconnect (kein Klick, kein Aussetzer). Icecast-Fallback-Mount übernimmt automatisch das Zurückschalten auf Playlist, falls kein Bus mehr aktiv ist.

**Zugriffswege (hybrid, wie ursprünglich gewünscht):**
1. **Lokal:** Outdoor-AP am Turm strahlt ein eigenes WLAN ab, das nur den Icecast-Stream des Pi erreichbar macht – funktioniert ohne Internetverbindung.
2. **Extern/mobil:** cloudflared läuft als eingebauter Bestandteil der Software (kein separater VPS nötig) und exposed Stream + Listener-UI + Admin-UI über einen Named Tunnel auf eine feste Subdomain.

## 3. Software-Stack

- **Backend:** Python, FastAPI + WebSockets (für Live-Updates zwischen Admin-UI, Listener-UI und Serverzustand).
- **Datenhaltung:** SQLite-Datei (Segmente, Busse, Shows/Tage, Sendezeiten, Admin-Auth) + `media/`-Ordner für hochgeladene Audiodateien (Jingles, Intros, Outros, Interview-Vorabaufnahmen etc.).
- **Audio:** ALSA/PipeWire für Geräteerkennung, Loopback und Routing; `ffmpeg` für den Dauerstream an Icecast; Icecast2 als Streaming-Server mit Fallback-Mount.
- **Tunnel:** `cloudflared` als Subprozess/systemd-Sidecar, über Named Tunnel + feste Subdomain (Config im Repo als Vorlage, Token via `.env`, nicht eingecheckt).
- **Frontend:** zwei separate, schlanke Web-UIs (siehe unten), kein schweres Frontend-Framework nötig – Vanilla JS oder ein leichtes Setup reicht.

## 4. Datenmodell

### Segment
```
Segment
 ├─ id
 ├─ type: song | interview | spotify | jingle | news | speech | ...
 ├─ title
 ├─ time (geplante Uhrzeit, Orientierung, kein hartes Muss)
 ├─ planned_duration (Sekunden)
 ├─ fixed: bool               // markiert "Fixpunkt" (z.B. feste News-Zeit)
 ├─ notes: text|null          // z.B. Stichpunkte für Ansagen
 ├─ media_file: path|null     // z.B. Intro/Outro/vorab aufgenommene Datei
 ├─ auto_route: [bus_id]      // welche Busse bei Aktivierung unmuted werden
 └─ children: [Segment]       // eine Verschachtelungsebene, z.B.
                              //   Interview → [Intro-Jingle, Talk-Block, Outro-Jingle]
```
Verschachtelung bewusst auf **eine Ebene** begrenzt (Kinder haben keine eigenen Kinder) – reicht für den Anwendungsfall und hält die UI übersichtlich.

### Bus (Audioquelle)
```
Bus
 ├─ device_id            // ALSA/PipeWire-Geräte-ID, zur Wiedererkennung nach Neustart
 ├─ display_name         // vom Team vergeben, z.B. "Bandraum-Pult"
 ├─ is_muted: bool
 └─ last_seen_active     // für Pegelanzeige / Verbindungsstatus
```
Busse werden **automatisch erkannt** (ALSA/PipeWire-Geräteliste + udev-Hotplug-Events), nicht im Code fest verdrahtet. Neu angeschlossene Geräte erscheinen ohne Neustart als neuer Bus in der UI; Zuordnung Geräte-ID → Anzeigename wird dauerhaft gespeichert.

### Show / Tag
```
Show (Tag)
 ├─ id, label (z.B. "Tag 3 – Mittwoch")
 └─ segments: [Segment]   // geordnete Liste, per Drag-and-Drop sortierbar
```

### Sendezeiten (öffentlich, getrennt von den Segment-Uhrzeiten)
```
ScheduleEntry
 └─ day, from, to, title, public: bool     // ob es in der Listener-UI angezeigt wird
```

### Admin-Auth
```
AdminUser
 └─ password_hash (bcrypt/argon2, nie Klartext), setup_code_used: bool
```

## 5. Admin-UI – Funktionsumfang

**Tage/Shows-Liste** (Sidebar): Tage anlegen, auswählen, Anzahl Segmente je Tag auf einen Blick.

**Ablauf-Editor** (Rundown): Segmente hinzufügen/bearbeiten/löschen/per Drag-and-Drop umsortieren, Segmente mit Kindern aufklappbar, Datei-Upload direkt am Segment (Intro/Outro/Aufnahme), "Fixpunkt"-Markierung.

**Live-Steuerung:**
- Aktuelles Segment **massiv hervorgehoben**: eigener Panel-Rahmen in Warnfarbe, pulsierender "LIVE"-Badge – muss auch im Stress sofort auffallen.
- **Countdown** der verbleibenden Zeit des aktuellen Segments, inkl. Fortschrittsbalken; bei Overrun (Segment läuft länger als geplant) kippt die Anzeige sichtbar um (Farbe, "+"-Zähler statt Countdown).
- **Fixpunkt-Anzeige:** Restzeit bis zum nächsten als "fix" markierten Segment, berechnet aus der Kette der verbleibenden Segmentdauern.
- **"Als nächstes"-Vorschau** direkt sichtbar, ohne scrollen zu müssen.
- **Transport:** Zurück/Weiter zum Wechseln des aktiven Segments, ON-AIR/OFF-AIR-Umschalter.
- **Notfall-Buttons** (gut erreichbar, visuell abgesetzt): "SOS – Playlist" (alle Live-Busse stumm, nur Player-Bus aktiv), "Alles stumm", "Technischer Unterbruch" (Platzhalter-Hinweis für Hörer:innen). Alle drei lösen einen deutlichen Banner-Hinweis aus, bis er quittiert wird.
- **Audio-Busse:** dynamisch erkannte Liste, je Bus ein Mute/Unmute-Schalter **und** eine Pegelanzeige (echte Analyse über PipeWire-Monitor-Ports/Web-Audio, zeigt ob tatsächlich Signal ankommt).
- **Notizen pro Segment:** Textfeld direkt am aktuellen Segment, gespeichert pro Segment. Zusätzlich ein **Pop-out-Button**, der ein zweites Browserfenster öffnet (für zweiten Bildschirm/Tablet) mit grossem Countdown, "Als nächstes" und denselben Notizen, live synchronisiert.

**Export/Import eines Tages:**
- Export als **`.zip`**, nicht nur JSON: enthält `tag.json` (kompletter Rundown inkl. Referenzen) plus `media/`-Unterordner mit genau den Audiodateien, die in diesem Tag referenziert werden.
- Import entpackt das Zip, kopiert Mediendateien in den lokalen `media/`-Ordner (Namenskollisionen per Hash-Suffix auflösen) und liest danach `tag.json` ein – damit ist ein exportierter Tag komplett portabel (USB-Stick, anderer Pi, egal).

**Sendezeiten-Tab:** eigene, öffentlich sichtbare Grobübersicht (getrennt von den minutengenauen Segment-Zeiten im Ablauf), die in der Listener-UI erscheint.

**Software-Update:** Bereich mit aktueller Version (Commit-Hash/Datum), Button "Nach Updates suchen" und "Jetzt aktualisieren" – zieht die neueste Version vom Git-Repository und startet die Anwendung selbständig neu, ohne den laufenden Stream zu unterbrechen.

## 6. Listener-UI – Funktionsumfang

Bewusst minimal: Play/Stop-Button für den Stream, Anzeige der öffentlichen Sendezeiten (aus dem Sendezeiten-Tab), evtl. Anzeige des aktuell laufenden Segment-Titels. Kein Login nötig, für alle offen (lokal wie extern über die Cloudflare-Subdomain).

## 7. Auth-Flow (Admin-Bereich)

Da die Admin-UI über die öffentliche Subdomain erreichbar ist, muss verhindert werden, dass irgendwer zuerst draufklickt und sich das Passwort schnappt:

1. Beim allerersten Start generiert der Pi automatisch einen **Setup-Code** (z.B. 6-stellig) und zeigt ihn nur dort, wo physischer Zugriff nötig ist (Terminal-Log auf dem Pi, o.ä.).
2. Die "Passwort setzen"-Seite verlangt zuerst diesen Code – erst danach kann das eigentliche Admin-Passwort gewählt werden. Der Code verfällt nach einmaliger Nutzung.
3. Danach normaler Login mit Passwort (bcrypt/argon2-Hash in der SQLite-DB) + Session-Cookie.
4. Der Admin-Login ist über einen Button auf der Listener-UI erreichbar ("Admin"), führt zur Passwort-/Login-Maske.

## 8. Sicherheit / Betrieb

- Cloudflare-Tunnel-Token und alle Secrets in `.env`, **nicht** ins Git-Repo (`.gitignore`).
- Regelmässige Sicherung von SQLite-DB + `media/`-Ordner (z.B. Cronjob auf USB-Stick oder ins Homelab), nicht nur auf manuellen Export verlassen.
- Geräte-Namenszuordnung (Bus-ID → Anzeigename) persistieren, damit nach Neustart nichts neu benannt werden muss.

## 9. Bewusst nicht verwendet (Scope-Entscheidungen)

- **Kein Liquidsoap** – für den gewünschten Funktionsumfang (Mischpult als Quelle + einfache Playlist + zwei schlanke WebUIs) overkill; die ALSA-Loopback-Bus-Lösung deckt denselben Bedarf mit weniger Komplexität ab.
- **Kein spotifyd/librespot** – Spotify läuft stattdessen über einen Laptop, der direkt (analog/USB) am Mischpult hängt.
- **Keine separate VPS** – cloudflared läuft eingebaut auf dem Pi, ersetzt einen extern gehosteten Relay-Server.

## 10. Offene Punkte für spätere Iterationen

- Echte Pegelmessung der Busse (PipeWire-Monitor-Ports / Web Audio API) – als `ffmpeg -af astats`-Messprozess pro Bus umgesetzt, aber nur auf echter Hardware verifizierbar.
- Emergency-Buttons steuern echtes Audio-Routing an (Mute auf PipeWire-Ebene), nicht nur UI-Zustand – ebenfalls nur auf echter Hardware verifizierbar.
- Feingranulare Rechte (falls später mehr als eine Person parallel Admin-Zugriff braucht) – aktuell reicht ein einzelner Admin-Account.

---

*Ein UI-Mockup (statisch, nicht ans Backend angebunden) für die Admin-Oberfläche existiert als HTML-Referenz für Layout, Farbschema (Konsolen-/Broadcast-Look, dunkel, mit Live-Warnfarbe für das aktuelle Segment) und Interaktionsfluss – siehe `frontend/admin/`, das daraus abgeleitet und ans Backend angebunden wurde.*
