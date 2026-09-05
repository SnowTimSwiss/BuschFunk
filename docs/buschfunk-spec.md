# BuschFunk – technische Spezifikation

Lagerradio für das Regiolager 27. Läuft auf einem Raspberry Pi (oder beliebigem Linux-Rechner) vor Ort, streamt lokal per WLAN und öffentlich per Cloudflare Tunnel, wird über eine Web-Admin-UI bedient. Lizenz: **GPLv3** (AGPLv3 falls je eine gehostete/SaaS-Variante entsteht).

## 1. Rahmenbedingungen

- Lagerplatz ca. 2 Hektar, Turm/Mast 5–10 m Höhe für Antenne/Outdoor-AP verfügbar.
- Strom: entweder Netzstrom vor Ort, sonst Jackery + Solarpanel. Geschätzte Dauerlast der Technik: ~20–35 W (Pi, USB-Audiointerface, Outdoor-AP, ggf. 4G-Router).
- Sendebetrieb: ca. 1–2 h Live-Sendung pro Tag, den Rest der Zeit läuft Musik aus der Mediathek.
- Erwartete Hörerzahl: max. ca. 50, gleichzeitig über WLAN vor Ort und mobil/extern.
- Bestehendes Equipment: analoges Mischpult, diverse Mikrofone aus dem Bandraum (u.a. Shure Beta 58 – supercardioid, für Live-Vocals/Instrumente geeignet, für Interviews eher ein Mikro mit breiterer Charakteristik verwenden).
- Bedient wird das Ganze von Leuten, die nebenher noch das Lager schmeissen: alles muss ohne Einarbeitung, im Stehen, auf einem Handy bedienbar sein.

## 2. Architektur-Überblick

**Kernidee des Audio-Signalwegs:** Alle Quellen speisen dauerhaft in einen PipeWire-Loopback-Bus (`buschfunk-mix`) ein – das angeschlossene Mischpult, weitere USB-Audiogeräte, und dazu die beiden internen Wiedergabe-Kanäle (Musik und Jingles). Jede Quelle ist einzeln stumm-/lautschaltbar. Genau **ein** ffmpeg-Prozess liest diesen Loopback dauerhaft aus und streamt an Icecast – dadurch ist "auf Sendung / nicht auf Sendung" nur Mute/Unmute im Hintergrund, nie ein Stream-Reconnect (kein Klick, kein Aussetzer).

Musik und Jingles sind **zwei getrennte Streams in denselben Sink**: PipeWire summiert sie, deshalb kann ein Jingle über die laufende Musik gelegt werden, ohne irgendetwas zu stoppen.

**Zugriffswege (hybrid):**
1. **Lokal:** Outdoor-AP am Turm strahlt ein eigenes WLAN ab, das den Icecast-Stream des Pi erreichbar macht – funktioniert ohne Internetverbindung.
2. **Extern/mobil:** cloudflared läuft als eingebauter Bestandteil der Software (kein separater VPS nötig) und exposed Stream + Listener-UI + Admin-UI über einen Named Tunnel auf eine feste Subdomain.

## 3. Software-Stack

- **Backend:** Python, FastAPI + WebSockets (für Live-Updates zwischen Admin-UI, Listener-UI und Serverzustand).
- **Datenhaltung:** SQLite-Datei (Mediathek, Playlists, Geräte, Admin-Auth) + `media/`-Ordner für die hochgeladenen Audiodateien.
- **Audio:** PipeWire für Geräteerkennung, Loopback und Routing; `ffmpeg` für Wiedergabe, Pegelmessung und den Dauerstream an Icecast; Icecast2 als Streaming-Server.
- **Tunnel:** `cloudflared` als systemd-Sidecar über Named Tunnel + feste Subdomain (Config im Repo als Vorlage, Secrets via `.env`, nicht eingecheckt).
- **Frontend:** zwei separate, schlanke Web-UIs, Vanilla JS, kein Framework, keine externen Fonts.

## 4. Datenmodell

### Track (Mediathek)
```
Track
 ├─ id
 ├─ filename          // Datei in media/, kollisionsfrei benannt
 ├─ original_name     // wie die Datei beim Hochladen hiess
 ├─ title             // Anzeigename, jederzeit umbenennbar
 ├─ kind: music | jingle
 └─ duration          // Sekunden, beim Upload per ffprobe bestimmt
```
`kind` entscheidet nur darüber, wo der Titel auftaucht: Jingles landen zusätzlich als grosse Knöpfe im Jingle-Board. Ein Jingle kann trotzdem in einer Playlist stehen.

### Playlist
```
Playlist
 ├─ id, name          // z.B. "Morgenmusik", "Lagerfeuer"
 └─ items: [PlaylistItem]   // geordnete Liste, verweist auf Tracks
```
Ein Track darf mehrfach in derselben Playlist stehen; das Löschen einer Playlist lässt die Tracks in der Mediathek unangetastet.

### Bus (Audiogerät)
```
Bus
 ├─ device_id            // PipeWire-Node-Name, zur Wiedererkennung nach Neustart
 ├─ display_name         // vom Team vergeben, z.B. "Bandraum-Pult"
 ├─ direction: in | out  // Quelle oder Wiedergabegerät (Monitor)
 ├─ is_muted, volume
 └─ last_seen_active
```
Busse werden **automatisch erkannt**, nicht im Code fest verdrahtet. Neu angeschlossene Geräte erscheinen ohne Neustart; Name, Mute und Lautstärke werden gespeichert und beim Wiedereinstecken automatisch aufs Gerät zurückgeschrieben.

### Sendezustand
```
LiveState
 └─ on_air: bool      // sind die Mikrofone offen?
```
Mehr Zustand gibt es nicht – der Player-Zustand (was läuft, was kommt) lebt im laufenden Prozess und wird per WebSocket verteilt.

### Admin-Auth
```
AdminUser
 └─ password_hash (bcrypt, nie Klartext) + einmaliger SetupCode
```

## 5. Admin-UI ("Regie") – Funktionsumfang

Eine einzige Seite, kein Modus-Wechsel: links das, was gerade passiert, rechts das Mischpult.

**Player:** Titel, Fortschrittsbalken, Start/Pause, Zurück/Weiter, Stopp, eigener Lautstärkeregler für die Musik und ein "endlos wiederholen"-Schalter (per Default an – Sendepausen sind der Feind). Darunter "Als nächstes" mit den kommenden Titeln; ein Klick springt hin, das ✕ nimmt einen Titel wieder raus.

**Jingle-Board:** alle als Jingle markierten Titel als grosse Knöpfe. Ein Tipp spielt sie **über** die laufende Musik, ohne sie zu stoppen.

**Mediathek:** Dateien per Drag-and-Drop oder Dateiauswahl hochladen (mehrere gleichzeitig), Titel umbenennen, als Jingle markieren, löschen. Pro Titel: sofort abspielen (der Rest der Warteschlange bleibt stehen und läuft danach weiter) oder ans Ende der Warteschlange hängen. Suchfeld für grössere Sammlungen.

**Playlists:** anlegen, umbenennen, löschen; Titel aus der Mediathek hinzufügen, umsortieren, entfernen. Eine Playlist lässt sich der Reihe nach starten, zufällig starten oder an die laufende Warteschlange anhängen.

**Auf Sendung:** ein grosser Schalter. "Auf Sendung" heisst: die Mikrofone gehen auf. Off Air schliesst alle Eingänge auf einmal, ohne die einzeln gesetzten Mute-Schalter zu überschreiben – die Musik läuft dabei weiter, der Stream reisst nie ab. Monitor-Ausgänge bleiben unberührt, im Regieraum hört man weiter mit.

**Mischpult-Ansicht:** aufgelistet wird nur, was tatsächlich am Pi hängt – keine Platzhalter, keine Default-Ausgänge. Je Gerät: Live-Pegel mit Peak-Hold, Lautstärkeregler (`wpctl set-volume`) und ein Stumm/An-Schalter. Geräte, die mal dran waren und gerade fehlen, stehen zusammengeklappt darunter und lassen sich vergessen.

**Master-Meter:** grosser Pegel des fertigen Mixes ("das geht raus") mit Klartext-Hinweis, ob gerade gar nichts rausgeht oder übersteuert wird.

**Immer erreichbar:** auf schmalen Bildschirmen liegt eine feste Leiste am unteren Rand mit dem Sendungs-Schalter und Zurück/Pause/Weiter – off air gehen ist immer einen Tipp entfernt, ohne zu scrollen. Alle Aktionen schalten die UI sofort um und lassen den Server nachziehen, statt auf die Antwort zu warten. Die Leertaste ist Start/Pause.

**Software-Update:** Bereich mit aktueller Version (Commit-Hash/Datum), "Nach Updates suchen" und "Jetzt aktualisieren" – zieht die neueste Version aus dem Git-Repository und startet die Anwendung selbständig neu, ohne den Icecast-Stream zu unterbrechen.

## 6. Listener-UI – Funktionsumfang

Bewusst minimal: Play/Stop und der Titel, der gerade läuft (bzw. "Live aus dem Lager", wenn die Mikrofone offen sind). Kein Login, für alle offen.

Dazu drei Dinge, die im Lager praktisch zählen:

- **Autostart:** die Seite verbindet sich beim Öffnen von selbst. Blockt der Browser Autoplay (Handy), erscheint stattdessen ein grosser "Antippen"-Knopf.
- **Hintergrund-Wiedergabe:** über die Media Session API laufen Titel und Play/Pause auf dem Sperrbildschirm; der Stream läuft weiter, wenn das Handy in die Tasche wandert.
- **Automatischer Reconnect:** reisst die Verbindung (WLAN-Rand, Stream-Neustart), verbindet die Seite mit wachsendem Abstand von selbst neu und landet dabei immer an der Live-Kante statt in einem alten Puffer.

## 7. Auth-Flow (Admin-Bereich)

Da die Admin-UI über die öffentliche Subdomain erreichbar ist, muss verhindert werden, dass irgendwer zuerst draufklickt und sich das Passwort schnappt:

1. Beim allerersten Start generiert der Pi einen **Setup-Code** (6-stellig) und schreibt ihn ins Log – dorthin kommt nur, wer physischen Zugriff hat.
2. Die "Passwort setzen"-Seite verlangt zuerst diesen Code. Der Code verfällt nach einmaliger Nutzung.
3. Danach normaler Login mit Passwort (bcrypt-Hash in der SQLite-DB) + Session-Cookie.

Solange noch kein Passwort gesetzt ist, erzeugt jeder Start einen frischen Code. Ist bereits ein Admin-Konto da, wird **kein** neuer Code ausgegeben – dann gilt das gesetzte Passwort.

## 8. Netzlast / WebSocket-Protokoll

Zwei Nachrichtentypen über `/ws/live`:

- `live_state` (1×/s, an alle): Sendezustand, Geräte, Player- und Jingle-Zustand inklusive der nächsten Titel.
- `meters` (5×/s, nur an Clients, die sie anfordern): Pegel, Master-Pegel, Abspielposition.

Die Regie abonniert die Meter, Hörer-Handys nicht – im Lager-WLAN soll niemand für Pegelanzeigen bezahlen, die er nie sieht. Von der Warteschlange gehen nur die nächsten 12 Titel über die Leitung, nicht die ganze Liste.

## 9. Sicherheit / Betrieb

- Cloudflare-Tunnel-Token und alle Secrets in `.env`, **nicht** ins Git-Repo (`.gitignore`).
- Regelmässige Sicherung von SQLite-DB + `media/`-Ordner (z.B. auf USB-Stick), die beiden zusammen sind das komplette Backup.
- Schema-Änderungen werden beim Start automatisch nachgezogen (`backend/app/db.py`), damit ein Update auf dem laufenden Pi nicht in einer kaputten Datenbank endet.

## 10. Bewusst nicht verwendet (Scope-Entscheidungen)

- **Kein Liquidsoap** – für Mischpult als Quelle + Playlist + zwei schlanke WebUIs overkill; die Loopback-Bus-Lösung deckt denselben Bedarf mit weniger Komplexität ab.
- **Kein spotifyd/librespot** – Musik kommt aus der eigenen Mediathek; ein Laptop kann zusätzlich analog/USB am Mischpult hängen.
- **Keine separate VPS** – cloudflared läuft eingebaut auf dem Pi.

**Bewusst wieder entfernt**, weil es in der Praxis mehr Verwaltung als Nutzen war:

- **Tagespläne / Ablauf-Editor / Sendezeiten** samt Countdown, Fixpunkten, Segment-Notizen, Pop-out-Fenster und Tages-Export/Import. Ein Lagerradio läuft spontan; ein minutengenauer Sendeplan, den vorher jemand pflegen muss, hilft dabei nicht. Was bleibt, ist das Technische: Musik, Jingles, Mikrofone, Pegel.
- **Notfall-Buttons** (SOS-Playlist / Alles stumm / Technischer Unterbruch) und der **Hell-Modus**. Stumm schalten geht direkt über den Sendungs-Schalter; ein zweites Farbschema kostet nur Pflege.

## 11. Offene Punkte für spätere Iterationen

- Pegelmessung, Wiedergabe und Lautstärkeregelung laufen über `ffmpeg` bzw. `wpctl` – auf echter Hardware verifizieren (siehe `docs/audio-setup.md`).
- Feingranulare Rechte (falls später mehr als eine Person parallel Admin-Zugriff braucht) – aktuell reicht ein einzelner Admin-Account.
- Ein Software-Update beendet die laufende Musik (der Icecast-Stream selbst läuft weiter). Für ein unterbrechungsfreies Update müsste der Wiedergabe-Prozess über den Neustart hinweg adoptiert werden.

---

*Farbschema: Konsolen-/Broadcast-Look, durchgehend dunkel, mit Live-Warnfarbe für "auf Sendung". Beide UIs kommen ohne externe Fonts und ohne Frontend-Framework aus – im Lager-WLAN gibt es oft kein Internet, und eine Seite, die auf Google Fonts wartet, ist genau dann langsam, wenn es drauf ankommt.*
