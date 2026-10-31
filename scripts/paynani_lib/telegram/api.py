"""
Cliente mínimo de la Bot API de Telegram (TELEGRAM.md §2), con la biblioteca estándar.

El token va en la ruta de la URL, como pide la Bot API. Por eso **ninguna excepción
de este módulo lleva la URL**: los errores dicen el método, el código HTTP y la
descripción de Telegram, y nada más. `urllib` pone la URL en sus propios errores;
aquí se atrapan y se reemplazan.
"""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request


class ApiError(Exception):
    """Telegram contestó `ok: false`. `code` es el `error_code` (o el HTTP)."""

    def __init__(self, method: str, code: int, description: str = "", retry_after: int | None = None):
        self.method = method
        self.code = code
        self.description = _clean(description)
        self.retry_after = retry_after
        super().__init__(f"{method}: {code} {self.description}".strip())


class Unauthorized(ApiError):
    """401: el token no vale (FR-7)."""


class Conflict(ApiError):
    """409: otro lector o un webhook (FR-3)."""


class RetryAfter(ApiError):
    """429: hay que esperar `retry_after` segundos (FR-26)."""


class NetworkError(Exception):
    """No se pudo hablar con Telegram (red, DNS, tiempo agotado, 5xx)."""

    def __init__(self, method: str, reason: str):
        self.method = method
        super().__init__(f"{method}: {reason}")


def _clean(text: str) -> str:
    """Una descripción de Telegram, corta y sin saltos de línea."""
    return " ".join(str(text or "").split())[:200]


class BotAPI:
    def __init__(self, token: str, base: str = "https://api.telegram.org"):
        self._token = token
        self._base = base.rstrip("/")

    def __repr__(self) -> str:          # nunca el token, ni en un traceback
        return "BotAPI(<token>)"

    def call(self, method: str, params: dict | None = None, *, timeout: float = 15.0):
        url = f"{self._base}/bot{self._token}/{method}"
        body = json.dumps({k: v for k, v in (params or {}).items() if v is not None}).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
            try:
                raw = exc.read()
            except OSError:
                raw = b""
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise NetworkError(method, type(reason).__name__ if not isinstance(reason, str) else "unreachable") from None
        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            data = {}
        if status >= 500:
            raise NetworkError(method, f"HTTP {status}")
        if isinstance(data, dict) and data.get("ok") is True:
            return data.get("result")
        code = int((data or {}).get("error_code") or status or 0)
        desc = (data or {}).get("description", "")
        retry = ((data or {}).get("parameters") or {}).get("retry_after")
        cls = {401: Unauthorized, 409: Conflict, 429: RetryAfter}.get(code, ApiError)
        raise cls(method, code, desc, int(retry) if retry else None) from None

    def download(self, file_path: str, limit_bytes: int, sink, *, timeout: float = 60.0) -> int:
        """Baja un archivo a `sink` (con .write) y corta al pasar `limit_bytes` (FR-18).

        Devuelve los bytes escritos; levanta ApiError(413) si el archivo pasa el límite.
        """
        safe = urllib.parse.quote(file_path, safe="/")
        url = f"{self._base}/file/bot{self._token}/{safe}"
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                total = 0
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        return total
                    total += len(chunk)
                    if total > limit_bytes:
                        raise ApiError("download", 413, "file larger than the limit")
                    sink.write(chunk)
        except urllib.error.HTTPError as exc:
            raise ApiError("download", exc.code, "download failed") from None
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError):
            raise NetworkError("download", "unreachable") from None
