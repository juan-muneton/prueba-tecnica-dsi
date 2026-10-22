"""SetTransactionStatus: clasifica el resultado de una transacción, lo guarda en
la cola y escribe una línea de log. Equivale a SetTransactionStatus.xaml.

- Sin excepción                -> EstadoExitoso, observación CUENTA_ENCONTRADA.
- BusinessRuleException        -> EstadoNegocio, observación de su código.
- SystemException              -> EstadoSistema, observación de su código.
- Cualquier otra excepción     -> EstadoSistema, ERROR_INTERNO (como en el
                                  REFramework: todo lo que no es negocio es sistema).

Devuelve la clave del estado para que Main cuente los errores de sistema seguidos.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable

from framework.exceptions import BusinessRuleException, SystemException
from framework.transaction_queue import TransactionQueue
from interactions.dispatcher import Transaction
from libs.jsonplaceholder_lib import QueryResult

LOGGER = logging.getLogger("consulta_cuentas")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def set_transaction_status(
    config: dict[str, Any],
    queue: TransactionQueue,
    transaction: Transaction,
    result: QueryResult | None = None,
    exception: BaseException | None = None,
    clock: Callable[[], str] = _now,
) -> str:
    account_id = transaction.account_id
    record: dict[str, Any] = {"fecha_consulta": clock()}

    if exception is None and result is not None:
        state, code, attempts = "EstadoExitoso", "CUENTA_ENCONTRADA", result.attempts
        record.update(user_id=result.account.user_id, title=result.account.title, body=result.account.body)
    elif isinstance(exception, BusinessRuleException):
        state, code, attempts = "EstadoNegocio", exception.codigo, exception.intentos
    elif isinstance(exception, SystemException):
        state, code, attempts = "EstadoSistema", exception.codigo, exception.intentos
    else:
        state, code, attempts = "EstadoSistema", "ERROR_INTERNO", 0

    record.update(estado=state, codigo=code, intentos=attempts)
    queue.save(account_id, record)  # persistir antes de reportar

    observation = config["Observaciones"][code].rstrip(".")
    if state == "EstadoSistema":
        # En un error interno el tipo de excepción es lo que sirve para el runbook
        detail = str(exception) if isinstance(exception, SystemException) else f"{type(exception).__name__}: {exception}"
        LOGGER.error("%s; id=%s codigo=%s intentos=%s detalle=%s", observation, account_id, code, attempts, detail)
    else:
        LOGGER.info("%s; id=%s codigo=%s intentos=%s", observation, account_id, code, attempts)
    return state
