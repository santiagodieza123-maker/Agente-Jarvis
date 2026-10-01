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
    pass


def _http_post(url: str, headers: dict, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, json.dumps(body).encode(), headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.load(e).get("error", {}).get("message", "")[:300]
        except Exception:
            pass
        raise LLMError(f"HTTP {e.code}: {detail}") from None   # sin cadena: no arrastra la petición
    except (urllib.error.URLError, TimeoutError) as e:
        raise LLMError(f"red: {type(e).__name__}") from None


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, timeout: float = 60.0,
                 post: Callable[[str, dict, dict, float], dict] = _http_post, retries: int = 2):
        if not api_key:
            raise ValueError("falta GEMINI_API_KEY")
        self._key, self.model, self.timeout, self._post, self.retries = api_key, model, timeout, post, retries

    @staticmethod
    def _contents(messages: list[dict]) -> list[dict]:
        """Historial como texto (user/model), fusionando turnos consecutivos del mismo rol.
        Las llamadas/resultados de herramientas van como texto: evita depender de firmas de pensamiento."""
        out: list[dict] = []
        for m in messages:
            role = "model" if m["role"] == "assistant" else "user"
            text = m["content"] if m["role"] != "tool" else f"[resultado de herramienta]\n{m['content']}"
            if out and out[-1]["role"] == role:
                out[-1]["parts"].append({"text": text})
            else:
                out.append({"role": role, "parts": [{"text": text}]})
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

        for attempt in range(self.retries + 1):
            try:
                data = self._post(url, headers, body, self.timeout)
                break
            except LLMError as e:
                transient = any(c in str(e) for c in ("HTTP 429", "HTTP 500", "HTTP 503", "red:"))
                if attempt == self.retries or not transient:
                    raise
                time.sleep(2 ** attempt)

        cands = data.get("candidates") or []
        if not cands:
            raise LLMError(f"respuesta sin candidatos: {data.get('promptFeedback', {})}")
        text, calls = [], []
        for part in cands[0].get("content", {}).get("parts", []):
            if "functionCall" in part:
                fc = part["functionCall"]
                calls.append(ToolCall(fc["name"], dict(fc.get("args", {}))))
            elif "text" in part and not part.get("thought"):
                text.append(part["text"])
        u = data.get("usageMetadata", {})
        return LLMResponse("".join(text), calls, u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0))
