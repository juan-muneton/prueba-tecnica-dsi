"""Dispatcher: lee el CSV tal como llega, valida cada línea y quita repetidos.

Equivale a Interactions\\Dispatcher.xaml: solo lee, no consulta la API ni
escribe nada. Devuelve las transacciones del lote (rama A de DECISIONES.md):

- Un id válido que se repite es una sola transacción con todas sus líneas (D1).
- Una línea inválida es su propia transacción, con su código del catálogo de
  observaciones, y no se consulta.
- El orden es el de la primera aparición de cada id en el archivo.
"""
from __future__ import annotations

import csv
import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from framework.exceptions import SystemException

LOGGER = logging.getLogger("consulta_cuentas")


@dataclass
class Transaction:
    raw_value: str                     # valor tal como llegó (columna ID Cuenta del Excel)
    lines: list[int] = field(default_factory=list)
    account_id: int | None = None      # número de cuenta si es válido
    invalid_code: str | None = None    # clave del catálogo si no es válido

    @property
    def is_valid(self) -> bool:
        return self.account_id is not None


@dataclass
class DispatcherResult:
    transactions: list[Transaction]
    fingerprint: str                   # sha256 del contenido: identifica el lote
    total_lines: int                   # líneas de datos, sin el encabezado

    @property
    def valid(self) -> list[Transaction]:
        return [t for t in self.transactions if t.is_valid]

    @property
    def invalid(self) -> list[Transaction]:
        return [t for t in self.transactions if not t.is_valid]

    @property
    def repeated(self) -> list[Transaction]:
        return [t for t in self.valid if len(t.lines) > 1]


def validate_value(value: str) -> tuple[int | None, str | None]:
    """Reglas de A2, en orden. Devuelve (número, None) o (None, código)."""
    clean = value.strip().strip('"').strip("'").strip()
    if not clean:
        return None, "LINEA_VACIA"
    # isascii evita que dígitos de otros alfabetos (p. ej. '٣') pasen por números
    if not (clean.isascii() and clean.isdecimal()):
        return None, "VALOR_NO_NUMERICO"
    number = int(clean)  # '007' -> 7: la API usa números
    if number < 1:
        return None, "CUENTA_FUERA_DE_RANGO"
    return number, None


def read_transactions(path: Path, column: str) -> DispatcherResult:
    if not path.is_file():
        raise SystemException("ENTRADA_NO_EXISTE", f"No existe el archivo de entrada: {path}")
    content = path.read_bytes()
    try:
        # utf-8-sig: acepta el BOM que deja Excel al guardar como CSV
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SystemException("ENTRADA_ILEGIBLE", f"El archivo no está en UTF-8: {path.name}") from exc

    reader = csv.reader(text.splitlines())
    header = next(reader, None) or []
    names = [name.strip().lower() for name in header]
    if column.lower() not in names:
        raise SystemException(
            "ENTRADA_SIN_COLUMNA", f"El archivo no tiene la columna '{column}'; encabezado leído: {header}"
        )
    index = names.index(column.lower())

    transactions: list[Transaction] = []
    by_id: dict[int, Transaction] = {}
    total_lines = 0
    for row in reader:
        total_lines += 1
        line = reader.line_num
        raw = row[index] if len(row) > index else ""
        number, code = validate_value(raw)
        if number is None:
            transactions.append(Transaction(raw_value=raw.strip(), lines=[line], invalid_code=code))
        elif number in by_id:
            by_id[number].lines.append(line)
        else:
            by_id[number] = Transaction(raw_value=str(number), lines=[line], account_id=number)
            transactions.append(by_id[number])

    return DispatcherResult(transactions, hashlib.sha256(content).hexdigest(), total_lines)


def dispatcher(config: dict[str, Any]) -> DispatcherResult:
    path: Path = config["ArchivoEntrada"]
    result = read_transactions(path, config["ColumnaReferencia"])
    LOGGER.info(
        "Archivo leído; archivo=%s huella=%s lineas=%s ids=%s repetidos=%s invalidas=%s",
        path.name,
        result.fingerprint[:8],
        result.total_lines,
        len(result.valid),
        len(result.repeated),
        len(result.invalid),
    )
    for t in result.repeated:
        LOGGER.info("Id repetido, se consulta una vez; id=%s lineas=%s", t.account_id, ",".join(map(str, t.lines)))
    for t in result.invalid:
        LOGGER.info("Línea inválida, no se consulta; linea=%s valor=%r codigo=%s", t.lines[0], t.raw_value, t.invalid_code)
    if not result.valid:
        LOGGER.info("Sin cuentas válidas para consultar; archivo=%s", path.name)
    return result
