"""Gemeinsame Pegel-Umrechnung fuer Mischpult- und Wiedergabe-Meter.

Alle Pegelquellen (Mischpult-Eingaenge, Kanalkorrektur, Musik/Jingle-Kanaele)
lesen denselben ffmpeg-astats-Wert (RMS in dB) aus und rechnen ihn ueber diese
eine Funktion in 0.0..1.0 um, damit alle Balken in der Regie gleich reagieren.
"""

LEVEL_FLOOR_DB = -60.0  # unterhalb davon gilt der Pegel als still


def db_to_level(db: float) -> float:
    if db <= LEVEL_FLOOR_DB:
        return 0.0
    return round(max(0.0, min(1.0, (db - LEVEL_FLOOR_DB) / -LEVEL_FLOOR_DB)), 3)
