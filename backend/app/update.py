"""Self-Update: `git pull` + Selbst-Neustart per os.execv.

os.execv() ersetzt nur das laufende Python-Programm-Image innerhalb
desselben Betriebssystem-Prozesses - Kindprozesse (allen voran der eine
Dauer-ffmpeg-Stream aus audio/stream.py) bleiben dabei unangetastet am
Leben, weil ihre Eltern-Kind-Beziehung eine Kernel-Tatsache ist, die von
`execv` nicht berührt wird. Ein Update unterbricht den laufenden Stream
also nicht - genau die "kein Aussetzer"-Philosophie der Spec, nur eben
für Software-Updates statt für Live/Playlist-Umschalten.

Damit braucht es weder systemd-Restart-Rechte noch sudo: der Prozess
startet sich einfach selbst neu, mit demselben Kommandozeilenaufruf.
"""

import asyncio
import logging
import os
import sys

from .config import REPO_ROOT
from .schemas import UpdateCheckResult, VersionInfo

logger = logging.getLogger("buschfunk.update")


class UpdateError(Exception):
    pass


async def _git(*args: str, timeout: float = 20.0) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=REPO_ROOT,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return -1, "", "timeout"
    return proc.returncode or 0, out.decode(errors="replace").strip(), err.decode(errors="replace").strip()


async def get_version_info() -> VersionInfo:
    _c1, commit, _e1 = await _git("rev-parse", "HEAD")
    _c2, commit_short, _e2 = await _git("rev-parse", "--short", "HEAD")
    _c3, commit_date, _e3 = await _git("log", "-1", "--format=%cI")
    _c4, branch, _e4 = await _git("rev-parse", "--abbrev-ref", "HEAD")
    code5, status, _e5 = await _git("status", "--porcelain")
    return VersionInfo(
        commit=commit or "unbekannt",
        commit_short=commit_short or "?",
        commit_date=commit_date or None,
        branch=branch or "?",
        dirty=bool(status) if code5 == 0 else False,
    )


async def check_for_update() -> UpdateCheckResult:
    code, branch, _err = await _git("rev-parse", "--abbrev-ref", "HEAD")
    branch = branch or "main"

    code, _out, err = await _git("fetch", "origin", branch, timeout=30.0)
    if code != 0:
        return UpdateCheckResult(up_to_date=True, behind_by=0, commits=[], error=err or "git fetch fehlgeschlagen")

    code, count_str, _err = await _git("rev-list", "--count", f"HEAD..origin/{branch}")
    behind_by = int(count_str) if count_str.isdigit() else 0

    commits: list[str] = []
    if behind_by > 0:
        _code, log_out, _err = await _git("log", f"HEAD..origin/{branch}", "--oneline", "--max-count=20")
        commits = [line for line in log_out.splitlines() if line.strip()]

    return UpdateCheckResult(up_to_date=behind_by == 0, behind_by=behind_by, commits=commits)


async def apply_update() -> None:
    """Zieht die neueste Version und markiert den Prozess für einen
    Selbst-Neustart, sobald die aktuelle Antwort raus ist (siehe
    routers/system.py, das dies als FastAPI-BackgroundTask aufruft)."""
    code, status, _err = await _git("status", "--porcelain")
    if code == 0 and status:
        raise UpdateError(
            "Lokale Änderungen im Repo gefunden - Update abgebrochen, um nichts zu überschreiben."
        )

    code, branch, _err = await _git("rev-parse", "--abbrev-ref", "HEAD")
    branch = branch or "main"

    code, _out, err = await _git("fetch", "origin", branch, timeout=30.0)
    if code != 0:
        raise UpdateError(f"git fetch fehlgeschlagen: {err}")

    code, out, err = await _git("pull", "--ff-only", "origin", branch, timeout=30.0)
    if code != 0:
        raise UpdateError(f"git pull fehlgeschlagen: {err or out}")

    logger.info("Update gezogen: %s", out)

    requirements = REPO_ROOT / "backend" / "requirements.txt"
    if requirements.exists() and "requirements.txt" in out:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "pip",
            "install",
            "-q",
            "-r",
            str(requirements),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        pip_out, pip_err = await proc.communicate()
        if proc.returncode != 0:
            logger.error("pip install nach Update fehlgeschlagen: %s", pip_err.decode(errors="replace"))


def restart_process() -> None:
    logger.warning("Self-Update: Prozess wird jetzt neu gestartet (os.execv) ...")
    os.execv(sys.executable, [sys.executable] + sys.argv)
