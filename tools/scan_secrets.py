"""Escáner de secretos para archivos versionados. Falla si encuentra una clave de API de Google/Gemini.
Uso: python tools/scan_secrets.py [--staged]   (sin opciones: todos los archivos versionados)
Se ejecuta en el hook pre-commit (tools/install_hooks.py), en pytest y en CI."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# Claves de prueba de este repo empiezan por AQ.test / AQ.falsa y se admiten.
PATTERNS = [re.compile(r"AQ\.(?!test|falsa)[A-Za-z0-9_-]{20,}"), re.compile(r"AIza[0-9A-Za-z_-]{35}")]


def local_secrets() -> list[str]:
    """Valores exactos de .env (si existe): ni siquiera un valor con otro formato debe llegar al repositorio."""
    env = REPO / ".env"
    if not env.is_file():
        return []
    out = []
    for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            v = line.split("=", 1)[1].strip().strip("\"'")
            if len(v) >= 12:
                out.append(v)
    return out


def tracked(staged: bool) -> list[str]:
    cmd = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"] if staged else ["git", "ls-files"]
    return subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, check=True).stdout.splitlines()


def scan(files: list[str], secrets: list[str] | None = None, staged: bool = False) -> list[str]:
    secrets = local_secrets() if secrets is None else secrets
    hits = []
    for name in files:
        if staged:
            r = subprocess.run(["git", "show", f":{name}"], cwd=REPO, capture_output=True)
            data = r.stdout.decode("utf-8", "ignore") if r.returncode == 0 else ""
        else:
            p = REPO / name
            try:
                if not p.is_file() or p.stat().st_size > 2_000_000:
                    continue
                data = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
        if any(pat.search(data) for pat in PATTERNS) or any(s in data for s in secrets):
            hits.append(name)
    return hits


def main(argv: list[str]) -> int:
    staged = "--staged" in argv
    hits = scan(tracked(staged), staged=staged)
    if hits:
        print("¡Posible secreto en: " + ", ".join(hits) + "! Quítalo antes de continuar.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
