"""Librería del sistema externo (jsonplaceholder), como las librerías de sistema
de mis proyectos internos en UiPath.

Encapsula la consulta de una cuenta y es la **única dueña del reintento**: quien
la usa no la envuelve en otro bucle de reintentos.

Frontera (rama B de DECISIONES.md):
- 200 con datos            -> devuelve la cuenta.
- 404                      -> BusinessRuleException CUENTA_NO_EXISTE, sin reintento.
- Timeout                  -> reintenta; agotado, SystemException TIMEOUT.
- Sin conexión             -> reintenta; agotado, SystemException SIN_CONEXION.
- 408, 429, 5xx (config)   -> reintenta; agotado, SystemException ERROR_HTTP.
- 200 que no se puede leer -> reintenta; agotado, SystemException RESPUESTA_INESPERADA.
- Otro código (400, 401…)  -> SystemException RESPUESTA_INESPERADA, sin reintento:
                              es configuración o permisos, reintentar no lo arregla.
"""
from __future__ import annotations

import json
import logging
import random
import socket
import time
from dataclasses import dataclass, field
from http.client import HTTPException
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from framework.exceptions import BusinessRuleException, SystemException

LOGGER = logging.getLogger("consulta_cuentas")


@dataclass
class HttpResponse:
    status: int
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)


class HttpTransport(Protocol):
    def get(self, url: str, timeout: float) -> HttpResponse: ...


class UrllibTransport:
    """Transporte real con la librería estándar (sin dependencias), como en mis proyectos internos."""

    def get(self, url: str, timeout: float) -> HttpResponse:
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "ConsultaCuentas/1.0"})
        try:
            with urlopen(request, timeout=timeout) as response:
                return HttpResponse(response.status, response.read(), dict(response.headers))
        except HTTPError as exc:
            # 4xx y 5xx llegan como excepción en urllib; aquí son una respuesta más
            return HttpResponse(exc.code, exc.read() or b"", dict(exc.headers or {}))


@dataclass
class Account:
    account_id: int
    user_id: Any
    title: str
    body: str


@dataclass
class QueryResult:
    account: Account
    attempts: int


def _is_timeout(exc: BaseException) -> bool:
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return True
    return isinstance(exc, URLError) and isinstance(exc.reason, (socket.timeout, TimeoutError))


def _parse_account(body: bytes, account_id: int) -> Account | None:
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("id") != account_id:
        return None
    if not all(key in data for key in ("userId", "title", "body")):
        return None
    return Account(account_id, data["userId"], str(data["title"]), str(data["body"]))


def _retry_after_seconds(headers: dict[str, str]) -> float | None:
    for name, value in headers.items():
        if name.lower() == "retry-after":
            try:
                return max(0.0, float(value))
            except ValueError:
                return None  # formato de fecha HTTP: se usa la espera creciente normal
    return None


class JsonPlaceholderLib:
    def __init__(
        self,
        config: dict[str, Any],
        transport: HttpTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self._url = config["ApiUrlBase"].rstrip("/") + config["ApiRutaConsulta"]
        self._timeout = float(config["ApiTimeoutSegundos"])
        self._max_attempts = int(config["MaxIntentos"])
        self._initial_wait = float(config["EsperaInicialSegundos"])
        self._factor = float(config["FactorEspera"])
        self._max_wait = float(config["EsperaMaximaSegundos"])
        self._retry_statuses = set(config["CodigosReintentables"])
        self._transport = transport or UrllibTransport()
        self._sleep = sleep
        self._jitter = jitter

    def url_for(self, account_id: int) -> str:
        return self._url.replace("{id}", str(account_id))

    def _wait_before(self, attempt: int, retry_after: float | None) -> float:
        """Espera antes del reintento que sigue al intento `attempt` (1, 2, 4 s…),
        con ±10 % al azar para no golpear al sistema todos a la vez."""
        if retry_after is not None:
            return min(retry_after, self._max_wait)
        wait = self._initial_wait * self._factor ** (attempt - 1)
        return min(wait * self._jitter(0.9, 1.1), self._max_wait)

    def get_account(self, account_id: int) -> QueryResult:
        url = self.url_for(account_id)
        for attempt in range(1, self._max_attempts + 1):
            retry_after = None
            try:
                response = self._transport.get(url, self._timeout)
            except (URLError, HTTPException, OSError) as exc:
                # socket.timeout y ConnectionError son OSError: entran aquí
                code = "TIMEOUT" if _is_timeout(exc) else "SIN_CONEXION"
                detail = type(exc).__name__
            else:
                if response.status == 200:
                    account = _parse_account(response.body, account_id)
                    if account:
                        return QueryResult(account, attempt)
                    code, detail = "RESPUESTA_INESPERADA", "http=200 cuerpo ilegible"
                elif response.status == 404:
                    raise BusinessRuleException("CUENTA_NO_EXISTE", "http=404", attempt)
                elif response.status in self._retry_statuses:
                    code, detail = "ERROR_HTTP", f"http={response.status}"
                    retry_after = _retry_after_seconds(response.headers)
                else:
                    raise SystemException("RESPUESTA_INESPERADA", f"http={response.status}", attempt)

            if attempt == self._max_attempts:
                raise SystemException(code, detail, attempt)
            wait = self._wait_before(attempt, retry_after)
            LOGGER.warning(
                "Reintento; id=%s codigo=%s detalle=%s intento=%s espera=%.1fs",
                account_id, code, detail, attempt, wait,
            )
            self._sleep(wait)
        raise AssertionError("inalcanzable: el bucle siempre devuelve o lanza")
