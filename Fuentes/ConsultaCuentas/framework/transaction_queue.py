"""Cola de transacciones del lote: lo resuelto y lo pendiente (rama C de DECISIONES.md).

Hace el papel de la cola de Orchestrator en mis robots:
- Un archivo JSON por lote en CarpetaCola, amarrado a la huella del CSV (C4): el
  mismo archivo relanzado retoma su cola; uno nuevo empieza limpio.
- Se guarda después de cada id, primero en un temporal y luego reemplazando el
  archivo (C1): una caída a mitad de escritura no lo daña.
- Resuelto = EstadoExitoso o EstadoNegocio; no se vuelve a consultar (C2).
  EstadoSistema y lo no consultado quedan pendientes para la siguiente ejecución.
- GetTransactionData sale de aquí: entrega el siguiente id pendiente o None.
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any

from framework.exceptions import SystemException
from interactions.dispatcher import DispatcherResult, Transaction

RESOLVED_STATES = ("EstadoExitoso", "EstadoNegocio")
QUEUE_VERSION = 1


def _write_atomic(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)  # en el mismo disco, el reemplazo es atómico


class TransactionQueue:
    def __init__(self, path: Path, data: dict[str, Any], batch: DispatcherResult) -> None:
        self.path = path
        self._data = data
        self._pending = [t for t in batch.valid if not self.is_resolved(t.account_id)]
        self.resolved_before = len(batch.valid) - len(self._pending)

    @classmethod
    def open(cls, config: dict[str, Any], batch: DispatcherResult, today: date | None = None) -> TransactionQueue:
        folder: Path = config["CarpetaCola"]
        path = folder / f"cola_{batch.fingerprint[:16]}.json"
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise SystemException("COLA_ILEGIBLE", f"No se puede leer la cola {path.name}") from exc
            if data.get("huella") != batch.fingerprint:
                raise SystemException("COLA_ILEGIBLE", f"La cola {path.name} es de otro archivo")
        else:
            today = today or date.today()
            data = {
                "version": QUEUE_VERSION,
                "huella": batch.fingerprint,
                "archivo_entrada": config["ArchivoEntrada"].name,
                "fecha_lote": today.isoformat(),
                "archivo_salida": cls._output_name(config, today),
                "items": {},
            }
            _write_atomic(path, data)
        return cls(path, data, batch)

    @staticmethod
    def _output_name(config: dict[str, Any], today: date) -> str:
        """resultado_cuentas_2026-10-22.xlsx; si ese día ya hay otro lote, _2, _3…"""
        taken = set()
        for other in config["CarpetaCola"].glob("cola_*.json"):
            try:
                taken.add(json.loads(other.read_text(encoding="utf-8")).get("archivo_salida"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
        base = f"{config['PrefijoOutput']}_{today.isoformat()}"
        name, n = f"{base}.xlsx", 1
        while name in taken:
            n += 1
            name = f"{base}_{n}.xlsx"
        return name

    @property
    def output_name(self) -> str:
        return self._data["archivo_salida"]

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def record(self, account_id: int) -> dict[str, Any] | None:
        return self._data["items"].get(str(account_id))

    def is_resolved(self, account_id: int) -> bool:
        record = self.record(account_id)
        return bool(record) and record["estado"] in RESOLVED_STATES

    def get_transaction_data(self) -> Transaction | None:
        return self._pending.pop(0) if self._pending else None

    def save(self, account_id: int, record: dict[str, Any]) -> None:
        self._data["items"][str(account_id)] = record
        _write_atomic(self.path, self._data)
