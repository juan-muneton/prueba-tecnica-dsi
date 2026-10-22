"""Process: trabaja una sola transacción. Equivale a BusinessProcess\\Process.xaml.

Solo orquesta: la consulta y sus reintentos son de la librería del sistema, y la
clasificación y el guardado son de SetTransactionStatus. No lee la configuración
ni abre conexiones por transacción: todo llega por argumentos.
Las excepciones (BusinessRuleException, SystemException) suben a Main.
"""
from __future__ import annotations

from typing import Any

from interactions.dispatcher import Transaction
from libs.jsonplaceholder_lib import JsonPlaceholderLib, QueryResult


def process(config: dict[str, Any], transaction: Transaction, lib: JsonPlaceholderLib) -> QueryResult:
    return lib.get_account(transaction.account_id)
