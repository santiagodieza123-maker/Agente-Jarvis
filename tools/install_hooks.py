"""Instala el hook pre-commit que ejecuta el escáner de secretos. Uso: python tools/install_hooks.py"""
import os
import stat
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOOK = '#!/bin/sh\nexec python tools/scan_secrets.py --staged\n'


def main() -> None:
    git_dir = Path(subprocess.run(["git", "rev-parse", "--git-path", "hooks"], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip())
    git_dir = git_dir if git_dir.is_absolute() else REPO / git_dir
    git_dir.mkdir(parents=True, exist_ok=True)
    hook = git_dir / "pre-commit"
    hook.write_text(HOOK, encoding="utf-8", newline="\n")
    if os.name != "nt":
        hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"Hook instalado en {hook}")


if __name__ == "__main__":
    main()
