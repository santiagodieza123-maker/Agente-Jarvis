"""Aviso (heurístico) cuando una acción por aprobar toca secretos: la carpeta de Jarvis, .env, claves SSH/nube o el
almacén de credenciales. No bloquea nada —la barrera real es la confirmación humana—, pero pone el motivo a la vista."""
from __future__ import annotations

import json
import re
from pathlib import Path

# (fragmento en minúsculas con '/' como separador, descripción)
MARKERS = [
    (".jarvis/", "la carpeta de configuración y secretos de Jarvis"),
    ("secrets.json", "el archivo de secretos de Jarvis"),
    ("audit.jsonl", "el registro de auditoría"),
    ("audit.anchor", "el ancla de auditoría"),
    ("permissions.json", "los permisos de Jarvis"),
    ("extensions.json", "la configuración de extensiones"),
    (".ssh/", "claves SSH"),
    ("id_rsa", "una clave privada SSH"),
    (".aws/", "credenciales de AWS"),
    (".azure/", "credenciales de Azure"),
    (".config/gcloud", "credenciales de Google Cloud"),
    ("cmdkey", "el administrador de credenciales de Windows"),
    ("vaultcmd", "el administrador de credenciales de Windows"),
    ("credential manager", "el administrador de credenciales de Windows"),
    ("get-credential", "credenciales de Windows"),
    ("keyring", "el almacén de claves del sistema"),
    ("gemini_api_key", "la clave de la API de Gemini"),
]


ENV_RE = re.compile(r"""(?:^|[\s/"'=:])\.env(?:$|[\s"'.,;)])""")


def _norm(text: str) -> str:
    return text.replace("\\", "/").lower()


def sensitive_hits(tool: str, args: dict, extra_paths: list[Path] | None = None) -> list[str]:
    """Descripciones únicas de lo sensible que aparece en la herramienta o en sus argumentos."""
    blob = _norm(json.dumps(args, ensure_ascii=False, default=str)) + " "
    hits: list[str] = []
    for frag, why in MARKERS:
        if frag in blob and why not in hits:
            hits.append(why)
    if ENV_RE.search(blob):
        hits.append("un archivo .env (suele contener claves)")
    for p in extra_paths or []:
        s = _norm(str(p))
        if s and s in blob and "la carpeta de configuración y secretos de Jarvis" not in hits:
            hits.append("la carpeta de configuración y secretos de Jarvis")
    return hits
