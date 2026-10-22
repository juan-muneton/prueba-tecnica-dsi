"""Arnés del paso 4: cola de transacciones y SetTransactionStatus (rama C). Sin red.

Ejecutar desde Fuentes/ConsultaCuentas:  python -m unittest discover -s tests -t .
"""
import json
import logging
import tempfile
import unittest
from datetime import date
from pathlib import Path

from framework.exceptions import BusinessRuleException, SystemException
from framework.init_all_settings import load_config
from framework.set_transaction_status import LOGGER, set_transaction_status
from framework.transaction_queue import TransactionQueue
from interactions.dispatcher import read_transactions
from libs.jsonplaceholder_lib import Account, QueryResult

DAY = date(2026, 10, 22)


def found(account_id, attempts=1):
    return QueryResult(Account(account_id, 1, "titulo", "cuerpo"), attempts)


class QueueTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = {**load_config(), "CarpetaCola": Path(self.tmp.name)}
        self.batch = read_transactions(self.config["ArchivoEntrada"], "id_cuenta")
        null = logging.NullHandler()
        LOGGER.addHandler(null)
        self.addCleanup(LOGGER.removeHandler, null)

    def open(self, batch=None):
        return TransactionQueue.open(self.config, batch or self.batch, today=DAY)

    def set_status(self, queue, transaction, result=None, exception=None):
        return set_transaction_status(self.config, queue, transaction, result, exception, clock=lambda: "2026-10-22 03:00:00")

    def drain(self, queue, how=lambda t: (found(t.account_id), None), limit=None):
        """Procesa la cola como lo hará Main: Get -> resultado -> Set."""
        done = []
        while limit is None or len(done) < limit:
            t = queue.get_transaction_data()
            if t is None:
                break
            result, exc = how(t)
            self.set_status(queue, t, result, exc)
            done.append(t.account_id)
        return done


class TransactionQueueTests(QueueTestCase):
    def test_new_queue_has_all_valid_ids_pending_in_order(self):
        queue = self.open()
        self.assertEqual(queue.pending_count, 15)
        self.assertEqual(queue.resolved_before, 0)
        self.assertEqual(queue.get_transaction_data().account_id, 7)
        self.assertEqual(queue.output_name, "resultado_cuentas_2026-10-22.xlsx")

    def test_second_run_does_not_query_resolved_ids(self):
        self.drain(self.open())
        again = self.open()
        self.assertEqual((again.pending_count, again.resolved_before), (0, 15))
        self.assertIsNone(again.get_transaction_data())

    def test_resumes_after_a_crash(self):
        first = self.drain(self.open(), limit=4)  # se "cae" tras 4 ids
        self.assertEqual(first, [7, 12, 23, 45])
        resumed = self.open()
        self.assertEqual(resumed.resolved_before, 4)
        self.assertEqual(self.drain(resumed)[0], 99)

    def test_business_is_resolved_system_stays_pending(self):
        def how(t):
            if t.account_id == 101:
                return None, BusinessRuleException("CUENTA_NO_EXISTE", "http=404", 1)
            if t.account_id == 23:
                return None, SystemException("TIMEOUT", "TimeoutError", 4)
            return found(t.account_id), None

        self.drain(self.open(), how)
        again = self.open()
        self.assertEqual(again.pending_count, 1)
        self.assertEqual(again.get_transaction_data().account_id, 23)
        self.assertEqual(again.record(101)["estado"], "EstadoNegocio")

    def test_file_is_saved_after_each_id_without_temp_left(self):
        queue = self.open()
        self.drain(queue, limit=2)
        saved = json.loads(queue.path.read_text(encoding="utf-8"))
        self.assertEqual(sorted(saved["items"]), ["12", "7"])
        self.assertEqual(list(Path(self.tmp.name).glob("*.tmp")), [])

    def test_new_file_starts_clean_and_same_day_gets_suffix(self):
        self.drain(self.open())
        other = read_transactions(self.write_csv(b"id_cuenta\n7\n"), "id_cuenta")
        queue = self.open(other)
        self.assertEqual(queue.pending_count, 1)
        self.assertEqual(queue.output_name, "resultado_cuentas_2026-10-22_2.xlsx")
        self.assertEqual(self.open().output_name, "resultado_cuentas_2026-10-22.xlsx")

    def test_unreadable_queue_stops(self):
        path = self.open().path
        path.write_text('{"huella": ', encoding="utf-8")
        with self.assertRaises(SystemException) as ctx:
            self.open()
        self.assertEqual(ctx.exception.codigo, "COLA_ILEGIBLE")

    def write_csv(self, content):
        path = Path(self.tmp.name) / "otro.csv"
        path.write_bytes(content)
        return path


class SetTransactionStatusTests(QueueTestCase):
    def setUp(self):
        super().setUp()
        self.queue = self.open()
        self.t = self.queue.get_transaction_data()  # id 7

    def test_success(self):
        with self.assertLogs("consulta_cuentas", "INFO") as logs:
            state = self.set_status(self.queue, self.t, found(7, attempts=2))
        self.assertEqual(state, "EstadoExitoso")
        self.assertEqual(self.queue.record(7), {
            "fecha_consulta": "2026-10-22 03:00:00", "user_id": 1, "title": "titulo", "body": "cuerpo",
            "estado": "EstadoExitoso", "codigo": "CUENTA_ENCONTRADA", "intentos": 2,
        })
        self.assertEqual(logs.output, ["INFO:consulta_cuentas:Cuenta encontrada; id=7 codigo=CUENTA_ENCONTRADA intentos=2"])

    def test_business_rule(self):
        with self.assertLogs("consulta_cuentas", "INFO") as logs:
            state = self.set_status(self.queue, self.t, exception=BusinessRuleException("CUENTA_NO_EXISTE", "http=404", 1))
        self.assertEqual(state, "EstadoNegocio")
        self.assertEqual(logs.output, ["INFO:consulta_cuentas:La cuenta no existe en el sistema; id=7 codigo=CUENTA_NO_EXISTE intentos=1"])

    def test_system_exception(self):
        with self.assertLogs("consulta_cuentas", "ERROR") as logs:
            state = self.set_status(self.queue, self.t, exception=SystemException("TIMEOUT", "TimeoutError", 4))
        self.assertEqual(state, "EstadoSistema")
        self.assertEqual(logs.output, [
            "ERROR:consulta_cuentas:El sistema no respondió a tiempo; se agotaron los reintentos; "
            "id=7 codigo=TIMEOUT intentos=4 detalle=TimeoutError"
        ])

    def test_unexpected_exception_is_system_internal_error(self):
        with self.assertLogs("consulta_cuentas", "ERROR") as logs:
            state = self.set_status(self.queue, self.t, exception=KeyError("userId"))
        self.assertEqual(state, "EstadoSistema")
        self.assertEqual(self.queue.record(7)["codigo"], "ERROR_INTERNO")
        self.assertIn("detalle=KeyError: 'userId'", logs.output[0])


if __name__ == "__main__":
    unittest.main()
