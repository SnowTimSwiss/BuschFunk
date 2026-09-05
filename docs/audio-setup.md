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
6. **Stream-Ausgang**: `ffmpeg -f pulse -i buschfunk-mix.monitor -t 3 -f null -`
   sollte 3 Sekunden lang ohne Fehler durchlaufen (Beweis, dass ffmpeg den
   Mix mitlesen kann - Voraussetzung für den Dauerstream in `audio/stream.py`).
7. **Pegelmessung**: BuschFunk hält pro Gerät *einen* dauerhaften ffmpeg-Prozess,
   der alle 100 ms einen RMS-Wert auf stdout schreibt. Von Hand nachstellen:
   `ffmpeg -f pulse -i <quelle> -af asetnsamples=n=4800:p=0,astats=metadata=1:reset=1,ametadata=mode=print:key=lavfi.astats.Overall.RMS_level:file=- -f null -`
   sollte fortlaufend `lavfi.astats.Overall.RMS_level=-xx.x` ausgeben, während
   Signal anliegt. Quelle ist bei Eingängen der Node-Name selbst, bei Ausgängen
   `<name>.monitor`; das Master-Meter liest `buschfunk-mix.monitor`.
8. **Lautstärke**: `wpctl set-volume <node-id> 0.80` sollte hörbar leiser machen
   (der Regler in der UI macht genau das, `wpctl set-mute` den Stumm-Schalter).
9. **Ausgänge (Monitor/Kopfhörer)**: angeschlossene Wiedergabegeräte (`media.class=Audio/Sink`,
   ausser `buschfunk-mix` selbst) sollten in der Admin-UI in der Live-Spalte
   unter "Angeschlossene Geräte" auftauchen. `pw-link -l` sollte Links von
   `buschfunk-mix:monitor_FL/FR` zum jeweiligen Gerät zeigen. Fehlen sie, manuell:
   `pw-link "buschfunk-mix:monitor_FL" "<gerät>:playback_FL"` (und FR). Mute
   funktioniert wie bei Eingängen über `wpctl set-mute <node-id> 1` auf dem
   Ausgabegerät - beeinflusst nicht den Icecast-Stream.

## Bekannte Stolpersteine

- Manche USB-Audiointerfaces brauchen ein paar Sekunden nach dem Einstecken,
  bis sie in `pw-dump` auftauchen (udev-Hotplug-Erkennung läuft alle 3s,
  siehe `main.py::_discover_buses_loop`).
- Gelesen wird überall über den `pulse`-Demuxer, nicht über `-f pipewire`:
  Debians ffmpeg-Paket ist ohne `--enable-libpipewire` gebaut. PipeWire stellt
  dafür `pipewire-pulse` bereit - Paket `pipewire-pulse` muss installiert und
  aktiv sein (`systemctl --user status pipewire-pulse`). Ein Sink wird über
  seine `.monitor`-Quelle mitgelesen, nie über den Sink-Namen selbst.
- Ein Sink taucht in der Pegelmessung nur auf, wenn `<name>.monitor` in
  `pactl list short sources` steht. Fehlt er dort, bleibt das Meter bei 0,
  ohne dass sonst etwas kaputt ist.
