# Audio-Setup auf dem Pi (Verifikation nötig)

Der Code in `backend/app/audio/pipewire.py` konnte in der Entwicklungs-
umgebung nicht gegen einen echten PipeWire-Server getestet werden (siehe
`docs/buschfunk-spec.md` Abschnitt 10). Vor dem Lager-Einsatz auf dem
echten Pi mit angeschlossenem Mischpult unbedingt durchgehen.

## Voraussetzungen auf dem Pi

- Raspberry Pi OS Bookworm oder neuer (PipeWire + WirePlumber als
  Standard-Audiosystem).
- Pakete: `ffmpeg`, `pipewire`, `wireplumber`, `pipewire-alsa`,
  `pipewire-audio-client-libraries`.
- Der BuschFunk-Dienst muss als **User-Service** (`systemctl --user`)
  laufen, nicht als root-System-Service - PipeWire läuft pro
  Benutzer-Session (siehe `deploy/systemd/buschfunk.service`).

## Manuelle Prüfschritte

1. **Mischpult erkennen**: `pw-dump | grep -A3 'media.class.*Audio/Source'`
   sollte das USB-Audiointerface/Mischpult auflisten. Falls nicht: USB-Kabel/
   Interface prüfen, `wpctl status` als Übersicht nutzen.
2. **Mix-Sink**: nach App-Start sollte `pw-cli ls Node | grep buschfunk-mix`
   einen Sink zeigen. Falls nicht, manuell testen:
   `pw-cli create-node adapter '{ factory.name=support.null-audio-sink node.name=buschfunk-mix media.class=Audio/Sink audio.position=[FL,FR] object.linger=true }'`
3. **Routing**: `pw-link -l` sollte Links vom Mischpult-Node zu
   `buschfunk-mix:playback_FL/FR` zeigen. Fehlen sie, manuell:
   `pw-link "<mischpult>:capture_FL" "buschfunk-mix:playback_FL"` (und FR).
4. **Mute**: `wpctl set-mute <node-id> 1` sollte das Signal stumm schalten,
   ohne den Link zu trennen (in `wpctl status` bleibt die Verbindung sichtbar).
5. **Player-Bus (Jingles)**: `PIPEWIRE_NODE=buschfunk-mix ffmpeg -re -i test.mp3 -f alsa pipewire`
   sollte hörbar über den Mix laufen. Falls "pipewire" als ALSA-PCM nicht
   gefunden wird: `pipewire-alsa` nachinstallieren.
6. **Stream-Ausgang**: `ffmpeg -f pipewire -i buschfunk-mix -t 3 -f null -`
   sollte 3 Sekunden lang ohne Fehler durchlaufen (Beweis, dass ffmpeg den
   Mix als PipeWire-Quelle lesen kann - Voraussetzung für den Dauerstream
   in `audio/stream.py`).
7. **Pegelmessung**: `ffmpeg -f pipewire -i <bus-name> -t 1 -af astats=metadata=1:reset=1 -f null - 2>&1 | grep RMS`
   sollte einen RMS-Wert ausgeben, während Signal anliegt.
8. **Ausgänge (Monitor/Kopfhörer)**: angeschlossene Wiedergabegeräte (`media.class=Audio/Sink`,
   ausser `buschfunk-mix` selbst) sollten in der Admin-UI unter Einstellungen ->
   Audio-Ausgänge auftauchen. `pw-link -l` sollte Links von
   `buschfunk-mix:monitor_FL/FR` zum jeweiligen Gerät zeigen. Fehlen sie, manuell:
   `pw-link "buschfunk-mix:monitor_FL" "<gerät>:playback_FL"` (und FR). Mute
   funktioniert wie bei Eingängen über `wpctl set-mute <node-id> 1` auf dem
   Ausgabegerät - beeinflusst nicht den Icecast-Stream.

## Bekannte Stolpersteine

- Manche USB-Audiointerfaces brauchen ein paar Sekunden nach dem Einstecken,
  bis sie in `pw-dump` auftauchen (udev-Hotplug-Erkennung läuft alle 3s,
  siehe `main.py::_discover_buses_loop`).
- `ffmpeg`'s PipeWire-Ein-/Ausgabe (`-f pipewire`) braucht eine mit
  `--enable-libpipewire` gebaute ffmpeg-Version. Raspberry Pi OS' Standard-
  ffmpeg-Paket sollte das mitbringen; mit `ffmpeg -devices | grep pipewire`
  prüfen.
- Falls `-f pipewire` bei ffmpeg fehlt: Alternative ist `-f alsa` mit
  `PIPEWIRE_NODE` (wie beim Player-Bus) auch für die Stream-Ausgabe -
  dann `audio/stream.py::_build_ffmpeg_cmd` entsprechend anpassen.
