"""Main: une las piezas en el orden de mi plantilla REFramework.

    Init      -> InitAllSettings (config.json, carpetas, log)
                 Dispatcher (lee y valida el CSV) y apertura de la cola del lote
    Get       -> TransactionQueue.get_transaction_data (siguiente id pendiente)
    Process   -> Process (consulta el id con la librería del sistema)
    Set       -> SetTransactionStatus (clasifica, guarda en la cola, log)
    End       -> EndProcess (Excel diario y resumen)

Corte (B4): tras MaxConsecutiveSystemExceptions errores de sistema seguidos deja
de consultar; lo que falta queda pendiente para la siguiente ejecución.

Códigos de salida: 0 todo resuelto · 2 quedaron errores de sistema pendientes ·
1 el proceso se detuvo (configuración, archivo de entrada, cola o Excel).

Uso:  python main.py [--config RUTA_CONFIG_JSON]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Callable

from business_process.process import process
from framework.end_process import end_process
from framework.exceptions import SystemException
from framework.init_all_settings import DEFAULT_CONFIG_PATH, LOGGER, init_all_settings, use_utf8_console
from framework.set_transaction_status import set_transaction_status
from framework.transaction_queue import TransactionQueue
from interactions.dispatcher import dispatcher
from libs.jsonplaceholder_lib import HttpTransport, JsonPlaceholderLib

EXIT_STOPPED = 1


def run(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    transport: HttpTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    # Init. Sin configuración válida no hay log todavía: el error va a la pantalla.
    use_utf8_console()
    try:
        config = init_all_settings(config_path)
    except SystemException as exc:
        print(f"Proceso detenido; codigo={exc.codigo} detalle={exc}", file=sys.stderr)
        return EXIT_STOPPED

    LOGGER.info("Proceso iniciado; proceso=%s", config["NombreProceso"])
    try:
        batch = dispatcher(config)
        if not batch.transactions:
            # Ruta sin insumo (A4): nada que consultar ni que reportar
            LOGGER.info("Proceso terminado sin insumo; archivo=%s", config["ArchivoEntrada"].name)
            return 0

        queue = TransactionQueue.open(config, batch)
        LOGGER.info(
            "Cola abierta; cola=%s pendientes=%s ya_resueltas=%s",
            queue.path.name, queue.pending_count, queue.resolved_before,
        )
        lib = JsonPlaceholderLib(config, transport, sleep=sleep)  # una sola vez, como InitAllApplications

        consulted, consecutive = 0, 0
        while (transaction := queue.get_transaction_data()) is not None:
            try:
                result, error = process(config, transaction, lib), None
            except Exception as exc:  # negocio, sistema o fallo interno: lo clasifica Set
                result, error = None, exc
            state = set_transaction_status(config, queue, transaction, result, error)
            consulted += 1
            consecutive = consecutive + 1 if state == "EstadoSistema" else 0
            if consecutive >= config["MaxConsecutiveSystemExceptions"]:
                LOGGER.error(
                    "API caída, se detienen las consultas; errores_seguidos=%s pendientes=%s",
                    consecutive, queue.pending_count,
                )
                break

        return end_process(config, batch, queue, consulted)
    except SystemException as exc:
        LOGGER.error("Proceso detenido; codigo=%s detalle=%s", exc.codigo, exc)
        return EXIT_STOPPED
    except Exception:
        LOGGER.exception("Proceso detenido por un error interno")
        return EXIT_STOPPED
    finally:
        LOGGER.info("Proceso finalizado")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Consulta las cuentas radicadas del CSV y deja el Excel diario.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Ruta de config.json")
    args = parser.parse_args(argv)
    return run(args.config)


if __name__ == "__main__":
    sys.exit(main())
