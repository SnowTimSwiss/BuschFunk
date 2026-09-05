"""Einstiegspunkt. Bewusst ein einfaches Skript mit knappem sys.argv (statt
`python -m uvicorn ...` mit vielen Flags) - app/update.py startet den
Prozess bei einem Self-Update per `os.execv(sys.executable, sys.argv)`
neu, das ist mit einem simplen, absoluten Skriptpfad am robustesten."""

import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        reload=False,
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
    )
