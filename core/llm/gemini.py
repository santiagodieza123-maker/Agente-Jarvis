"""Proveedor Gemini vía REST (sin SDK). La clave viaja solo en la cabecera x-goog-api-key."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Callable

from core.llm.provider import LLMProvider, LLMResponse, ToolCall

BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-3.1-flash-lite"


class LLMError(RuntimeError):
    def __init__(self, msg: str, retry_after: float | None = None):
        super().__init__(msg)
        self.retry_after = retry_after          # segundos que pide esperar el servidor (429), si los indica


MAX_QUOTA_WAIT = 45.0                           # no se espera más que esto por reintento; cuota diaria agotada = fallo claro
MAX_QUOTA_RETRIES = 3


def _retry_delay(err_json: dict) -> float | None:
    """`retryDelay` ("17s", "0.5s") de los detalles de un error 429 de Gemini."""
    for d in (err_json.get("error", {}).get("details") or []):
        v = d.get("retryDelay") if isinstance(d, dict) else None
        if isinstance(v, str) and v.endswith("s"):
            try:
                return float(v[:-1])
            except ValueError:
                pass
    return None


def _http_post(url: str, headers: dict, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, json.dumps(body).encode(), headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail, delay = "", None
        try:
            j = json.load(e)
            detail = j.get("error", {}).get("message", "")[:300]
            delay = _retry_delay(j) if e.code == 429 else None
        except Exception:
            pass
        raise LLMError(f"HTTP {e.code}: {detail}", retry_after=delay) from None   # sin cadena: no arrastra la petición
    except (urllib.error.URLError, TimeoutError) as e:
        raise LLMError(f"red: {type(e).__name__}") from None


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, timeout: float = 60.0,
                 post: Callable[[str, dict, dict, float], dict] = _http_post, retries: int = 2,
                 sleep: Callable[[float], None] | None = None):
        if not api_key:
            raise ValueError("falta GEMINI_API_KEY")
        self._key, self.model, self.timeout, self._post, self.retries = api_key, model, timeout, post, retries
        self._sleep = sleep or (lambda s: time.sleep(s))
        self.on_wait: Callable[[float, str], None] | None = None     # aviso al usuario mientras se espera (cuota, red)

    @staticmethod
    def _contents(messages: list[dict]) -> list[dict]:
        """Historial en el formato nativo de Gemini: las llamadas a herramientas van como functionCall (con su firma de
        pensamiento, que Gemini 3 exige devolver) y sus resultados como functionResponse. Así el modelo no imita un
        formato de texto en lugar de llamar a la herramienta. Turnos consecutivos del mismo rol se fusionan."""
        out: list[dict] = []

        def push(role: str, part: dict) -> None:
            if out and out[-1]["role"] == role:
                out[-1]["parts"].append(part)
            else:
                out.append({"role": role, "parts": [part]})

        for m in messages:
            if m["role"] == "assistant" and m.get("call"):
                c = m["call"]
                part: dict = {"functionCall": {"name": c["name"], "args": c.get("args") or {}}}
                if c.get("signature"):
                    part["thoughtSignature"] = c["signature"]
                push("model", part)
            elif m["role"] == "tool" and m.get("name"):
                push("user", {"functionResponse": {"name": m["name"], "response": {"result": m["content"]}}})
            elif m["role"] == "assistant":
                push("model", {"text": m["content"]})
            elif m["role"] == "tool":
                push("user", {"text": f"[resultado de herramienta]\n{m['content']}"})
            else:
                push("user", {"text": m["content"]})
        return out

    def generate(self, system, messages, tools, image_png=None) -> LLMResponse:
        contents = self._contents(messages)
        if image_png:
            import base64
            contents[-1]["parts"].append({"inline_data": {"mime_type": "image/png", "data": base64.b64encode(image_png).decode()}})
        body: dict = {"systemInstruction": {"parts": [{"text": system}]}, "contents": contents}
        if tools:
            body["tools"] = [{"functionDeclarations": tools}]
        url = f"{BASE}/models/{self.model}:generateContent"
        headers = {"Content-Type": "application/json", "x-goog-api-key": self._key}

        attempt = quota_waits = 0
        while True:
            try:
                data = self._post(url, headers, body, self.timeout)
                break
            except LLMError as e:
                if "HTTP 429" in str(e):
                    wait = e.retry_after if e.retry_after is not None else 5.0 * (quota_waits + 1)
                    if quota_waits >= MAX_QUOTA_RETRIES or wait > MAX_QUOTA_WAIT:
                        raise LLMError(f"cuota de Gemini agotada" + (f"; reintenta en {int(wait)} s" if e.retry_after else "") +
                                       f" ({str(e)[:160]})", e.retry_after) from None
                    quota_waits += 1
                    if self.on_wait:
                        self.on_wait(wait, "cuota de Gemini")
                    self._sleep(wait + 0.5)
                    continue
                transient = any(c in str(e) for c in ("HTTP 500", "HTTP 503", "red:"))
                if attempt >= self.retries or not transient:
                    raise
                if self.on_wait:
                    self.on_wait(2 ** attempt, "red o servidor")
                self._sleep(2 ** attempt)
                attempt += 1

        cands = data.get("candidates") or []
        if not cands:
            raise LLMError(f"respuesta sin candidatos: {data.get('promptFeedback', {})}")
        text, calls = [], []
        for part in cands[0].get("content", {}).get("parts", []):
            if "functionCall" in part:
                fc = part["functionCall"]
                calls.append(ToolCall(fc["name"], dict(fc.get("args", {})), part.get("thoughtSignature")))
            elif "text" in part and not part.get("thought"):
                text.append(part["text"])
        u = data.get("usageMetadata", {})
        return LLMResponse("".join(text), calls, u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0))
