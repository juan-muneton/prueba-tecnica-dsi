"""Arnés del paso 3: librería de la API y sus reintentos (rama B). Sin red.

El transporte falso devuelve, en orden, las respuestas o errores del guion; la
espera se registra en vez de dormir, para comprobar la espera creciente.

Ejecutar desde Fuentes/ConsultaCuentas:  python -m unittest discover -s tests -t .
"""
import json
import logging
import socket
import unittest
from urllib.error import URLError

from framework.exceptions import BusinessRuleException, SystemException
from framework.init_all_settings import load_config
from libs.jsonplaceholder_lib import LOGGER, HttpResponse, JsonPlaceholderLib

POST_7 = {"userId": 1, "id": 7, "title": "magnam facilis autem", "body": "dolore placeat"}


def ok(data=POST_7):
    return HttpResponse(200, json.dumps(data).encode("utf-8"))


class FakeTransport:
    def __init__(self, *script):
        self.script = list(script)
        self.calls = []

    def get(self, url, timeout):
        self.calls.append((url, timeout))
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step


class JsonPlaceholderLibTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()
        self.waits = []
        # Sin manejador, logging imprime los avisos sueltos en la salida de las pruebas
        null = logging.NullHandler()
        LOGGER.addHandler(null)
        self.addCleanup(LOGGER.removeHandler, null)

    def lib(self, *script, **overrides):
        self.transport = FakeTransport(*script)
        config = {**self.config, **overrides}
        return JsonPlaceholderLib(config, self.transport, sleep=self.waits.append, jitter=lambda a, b: 1.0)

    def assert_system(self, lib, code, attempts):
        with self.assertRaises(SystemException) as ctx:
            lib.get_account(7)
        self.assertEqual((ctx.exception.codigo, ctx.exception.intentos), (code, attempts))
        self.assertEqual(len(self.transport.calls), attempts)

    def test_found_first_try(self):
        result = self.lib(ok()).get_account(7)
        self.assertEqual((result.account.user_id, result.account.title, result.attempts), (1, "magnam facilis autem", 1))
        self.assertEqual(self.transport.calls, [("https://jsonplaceholder.typicode.com/posts/7", 10.0)])
        self.assertEqual(self.waits, [])

    def test_404_is_business_and_not_retried(self):
        lib = self.lib(HttpResponse(404, b"{}"))
        with self.assertRaises(BusinessRuleException) as ctx:
            lib.get_account(7)
        self.assertEqual((ctx.exception.codigo, ctx.exception.intentos), ("CUENTA_NO_EXISTE", 1))
        self.assertEqual(self.waits, [])

    def test_503_then_found_waits_1_then_2(self):
        result = self.lib(HttpResponse(503, b""), HttpResponse(503, b""), ok()).get_account(7)
        self.assertEqual(result.attempts, 3)
        self.assertEqual(self.waits, [1.0, 2.0])

    def test_timeout_exhausted_waits_1_2_4(self):
        lib = self.lib(socket.timeout(), TimeoutError(), URLError(socket.timeout()), socket.timeout())
        self.assert_system(lib, "TIMEOUT", 4)
        self.assertEqual(self.waits, [1.0, 2.0, 4.0])

    def test_no_connection_exhausted(self):
        lib = self.lib(*[URLError(ConnectionRefusedError())] * 3, ConnectionResetError())
        self.assert_system(lib, "SIN_CONEXION", 4)

    def test_retryable_status_exhausted(self):
        lib = self.lib(*[HttpResponse(code, b"") for code in (500, 502, 504, 408)])
        self.assert_system(lib, "ERROR_HTTP", 4)

    def test_other_4xx_is_not_retried(self):
        for status in (400, 401, 403):
            with self.subTest(status=status):
                self.waits.clear()
                self.assert_system(self.lib(HttpResponse(status, b"")), "RESPUESTA_INESPERADA", 1)
                self.assertEqual(self.waits, [])

    def test_unreadable_200_is_retried(self):
        result = self.lib(HttpResponse(200, b"<html>proxy</html>"), ok()).get_account(7)
        self.assertEqual(result.attempts, 2)

    def test_200_of_another_id_is_unexpected(self):
        lib = self.lib(*[ok({**POST_7, "id": 8})] * 4)
        self.assert_system(lib, "RESPUESTA_INESPERADA", 4)

    def test_404_after_a_retry_keeps_attempt_count(self):
        lib = self.lib(socket.timeout(), HttpResponse(404, b"{}"))
        with self.assertRaises(BusinessRuleException) as ctx:
            lib.get_account(7)
        self.assertEqual(ctx.exception.intentos, 2)

    def test_retry_after_is_respected_with_cap(self):
        lib = self.lib(
            HttpResponse(429, b"", {"Retry-After": "5"}),
            HttpResponse(429, b"", {"retry-after": "100"}),
            HttpResponse(503, b"", {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}),
            ok(),
        )
        lib.get_account(7)
        self.assertEqual(self.waits, [5.0, 30.0, 4.0])

    def test_wait_never_exceeds_max(self):
        lib = self.lib(*[socket.timeout()] * 6, MaxIntentos=6, EsperaInicialSegundos=10)
        self.assert_system(lib, "TIMEOUT", 6)
        self.assertEqual(self.waits, [10.0, 20.0, 30.0, 30.0, 30.0])

    def test_one_attempt_means_no_retry(self):
        self.assert_system(self.lib(socket.timeout(), MaxIntentos=1), "TIMEOUT", 1)
        self.assertEqual(self.waits, [])

    def test_retry_is_logged_as_sentence_then_data(self):
        lib = self.lib(socket.timeout(), ok())
        with self.assertLogs("consulta_cuentas", "WARNING") as logs:
            lib.get_account(7)
        self.assertEqual(logs.records[0].getMessage(), "Reintento; id=7 codigo=TIMEOUT detalle=TimeoutError intento=1 espera=1.0s")

    def test_jitter_stays_within_ten_percent(self):
        lib = JsonPlaceholderLib(self.config, FakeTransport(), sleep=self.waits.append)
        for _ in range(200):
            self.assertTrue(0.9 <= lib._wait_before(1, None) <= 1.1)


if __name__ == "__main__":
    unittest.main()
