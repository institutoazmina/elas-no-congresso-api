#!/usr/bin/env python
"""Entrypoint do serviço web: migra e sobe o uvicorn.

A imagem runtime é distroless (sem shell), então não dá para encadear
`migrate && uvicorn` com `sh -c`. Este script faz o mesmo em Python puro:
roda a migração e depois substitui o processo pelo uvicorn via os.execvp.
"""

import os
import subprocess
import sys

PORT = os.environ.get("PORT", "8000")


def main() -> None:
    subprocess.run(
        [sys.executable, "manage.py", "migrate", "--noinput"],
        check=True,
    )
    os.execvp(
        sys.executable,
        [
            sys.executable,
            "-m",
            "uvicorn",
            "config.asgi:application",
            "--host",
            "0.0.0.0",
            "--port",
            PORT,
            "--no-access-log",
        ],
    )


if __name__ == "__main__":
    main()
