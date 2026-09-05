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

**Tage/Shows-Liste** (Sidebar): Tage anlegen, umbenennen, löschen, auswählen; Anzahl Segmente je Tag auf einen Blick.

**Ablauf-Editor** (Rundown): Segmente hinzufügen/bearbeiten/löschen/per Drag-and-Drop umsortieren, Unterpunkte direkt an der Segmentzeile anlegen, "Fixpunkt"-Markierung. Datei-Upload direkt am Segment, dabei wird zusätzlich festgelegt, **was** die Datei ist (Intro / Outro / Aufnahme / Jingle) und **wann** sie läuft (automatisch beim Segmentstart, automatisch am geplanten Ende, oder nur auf Knopfdruck). Automatisch gestartete Dateien laufen nur, wenn ON AIR ist.

**Live-Steuerung:**
- Aktuelles Segment **massiv hervorgehoben**: eigener Panel-Rahmen in Warnfarbe, pulsierender "LIVE"-Badge – muss auch im Stress sofort auffallen.
- **Countdown** der verbleibenden Zeit des aktuellen Segments, inkl. Fortschrittsbalken; bei Overrun (Segment läuft länger als geplant) kippt die Anzeige sichtbar um (Farbe, "+"-Zähler statt Countdown).
- **Fixpunkt-Anzeige:** Restzeit bis zum nächsten als "fix" markierten Segment, berechnet aus der Kette der verbleibenden Segmentdauern.
- **"Als nächstes"-Vorschau** direkt sichtbar, ohne scrollen zu müssen.
- **Transport:** Zurück/Weiter zum Wechseln des aktiven Segments, ON-AIR/OFF-AIR-Umschalter.
- **Transport bleibt jederzeit erreichbar:** auf schmalen Bildschirmen liegt eine feste Leiste am unteren Rand mit Zurück/Weiter, Countdown und dem ON-AIR/OFF-AIR-Schalter - Off Air gehen ist immer einen Tipp entfernt, ohne zu scrollen. Alle Transport-Aktionen schalten die UI sofort um und lassen den Server nachziehen, statt auf die Antwort zu warten.
- **Mischpult-Ansicht:** aufgelistet wird nur, was tatsächlich am Pi hängt - keine Platzhalter, keine Default-Ausgänge. Je Gerät: Live-Pegelanzeige mit Peak-Hold, Lautstärkeregler (`wpctl set-volume`) und ein Stumm/An-Schalter. Namen und Lautstärken bleiben gespeichert und werden beim Wiedereinstecken automatisch aufs Gerät zurückgeschrieben. Geräte, die mal dran waren und gerade fehlen, stehen zusammengeklappt darunter und lassen sich vergessen.
- **Master-Meter:** eigener, grosser Pegel des fertigen Mixes ("das geht raus") mit Klartext-Hinweis, ob gerade gar nichts rausgeht oder übersteuert wird.
- **Notizen pro Segment:** Textfeld direkt am aktuellen Segment, gespeichert pro Segment. Zusätzlich ein **Pop-out-Button**, der ein zweites Browserfenster öffnet (für zweiten Bildschirm/Tablet) mit grossem Countdown, "Als nächstes" und denselben Notizen, live synchronisiert.

**Export/Import eines Tages:**
- Export als **`.zip`**, nicht nur JSON: enthält `tag.json` (kompletter Rundown inkl. Referenzen) plus `media/`-Unterordner mit genau den Audiodateien, die in diesem Tag referenziert werden.
- Import entpackt das Zip, kopiert Mediendateien in den lokalen `media/`-Ordner (Namenskollisionen per Hash-Suffix auflösen) und liest danach `tag.json` ein – damit ist ein exportierter Tag komplett portabel (USB-Stick, anderer Pi, egal).

**Sendezeiten-Tab:** eigene, öffentlich sichtbare Grobübersicht (getrennt von den minutengenauen Segment-Zeiten im Ablauf), die in der Listener-UI erscheint.

**Software-Update:** Bereich mit aktueller Version (Commit-Hash/Datum), Button "Nach Updates suchen" und "Jetzt aktualisieren" – zieht die neueste Version vom Git-Repository und startet die Anwendung selbständig neu, ohne den laufenden Stream zu unterbrechen.

## 6. Listener-UI – Funktionsumfang

Bewusst minimal: Play/Stop, Anzeige der öffentlichen Sendezeiten (aus dem Sendezeiten-Tab) und des aktuell laufenden Segment-Titels. Kein Login nötig, für alle offen (lokal wie extern über die Cloudflare-Subdomain).

Dazu drei Dinge, die im Lager praktisch zählen:

- **Autostart:** die Seite verbindet sich beim Öffnen von selbst. Blockt der Browser Autoplay (Handy), erscheint stattdessen ein grosser "Antippen"-Knopf.
- **Hintergrund-Wiedergabe:** über die Media Session API laufen Titel und Play/Pause auf dem Sperrbildschirm; der Stream läuft weiter, wenn das Handy in die Tasche wandert.
- **Automatischer Reconnect:** reisst die Verbindung (WLAN-Rand, Stream-Neustart), verbindet die Seite mit wachsendem Abstand von selbst neu und landet dabei immer an der Live-Kante statt in einem alten Puffer.

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

- Pegelmessung und Lautstärkeregelung laufen über je einen dauerhaften `ffmpeg -af astats`-Prozess pro Gerät bzw. `wpctl set-volume` – auf echter Hardware noch zu verifizieren (siehe `docs/audio-setup.md`).
- Feingranulare Rechte (falls später mehr als eine Person parallel Admin-Zugriff braucht) – aktuell reicht ein einzelner Admin-Account.

**Bewusst wieder entfernt:** Notfall-Buttons (SOS-Playlist / Alles stumm / Technischer Unterbruch) samt Banner und der Hell-Modus. Stumm schalten geht direkt und schneller über die Geräteliste; ein zweites Farbschema kostet nur Pflege und hilft in einer abgedunkelten Regie niemandem.

---

*Farbschema: Konsolen-/Broadcast-Look, durchgehend dunkel, mit Live-Warnfarbe für das aktuelle Segment. Beide UIs kommen ohne externe Fonts und ohne Frontend-Framework aus – im Lager-WLAN gibt es oft kein Internet, und eine Seite, die auf Google Fonts wartet, ist genau dann langsam, wenn es drauf ankommt.*
