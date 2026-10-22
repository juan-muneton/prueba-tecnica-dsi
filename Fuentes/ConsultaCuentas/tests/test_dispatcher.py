"""Arnés del paso 2: Dispatcher (rama A). Sin red.

Ejecutar desde Fuentes/ConsultaCuentas:  python -m unittest discover -s tests -t .
"""
import tempfile
import unittest
from pathlib import Path

from framework.exceptions import SystemException
from framework.init_all_settings import load_config
from interactions.dispatcher import read_transactions, validate_value

REAL_CSV = load_config()["ArchivoEntrada"]


class ValidateValueTests(unittest.TestCase):
    def test_rules_in_order(self):
        cases = {
            "7": (7, None),
            '"42"': (42, None),
            ' "42" ': (42, None),
            "007": (7, None),
            "": (None, "LINEA_VACIA"),
            "   ": (None, "LINEA_VACIA"),
            "abc": (None, "VALOR_NO_NUMERICO"),
            "7.5": (None, "VALOR_NO_NUMERICO"),
            "-3": (None, "VALOR_NO_NUMERICO"),
            "٣": (None, "VALOR_NO_NUMERICO"),
            "0": (None, "CUENTA_FUERA_DE_RANGO"),
            "000": (None, "CUENTA_FUERA_DE_RANGO"),
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(validate_value(value), expected)


class ReadTransactionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, content: bytes) -> Path:
        path = self.dir / "cuentas.csv"
        path.write_bytes(content)
        return path

    def test_csv_of_the_challenge(self):
        result = read_transactions(REAL_CSV, "id_cuenta")
        rows = [(t.raw_value, t.lines, t.invalid_code) for t in result.transactions]
        self.assertEqual(rows, [
            ("7", [2, 6, 18], None),
            ("12", [3, 14], None),
            ("23", [4], None),
            ("45", [5], None),
            ("99", [7], None),
            ("101", [8], None),
            ("abc", [9], "VALOR_NO_NUMERICO"),
            ("3", [10], None),
            ("58", [11], None),
            ("", [12], "LINEA_VACIA"),
            ("88", [13], None),
            ("150", [15], None),
            ("64", [16], None),
            ("31", [17], None),
            ("42", [19], None),
            ("76", [20], None),
            ("0", [21], "CUENTA_FUERA_DE_RANGO"),
            ("19", [22], None),
        ])
        self.assertEqual(result.total_lines, 21)
        self.assertEqual(len(result.valid), 15)
        self.assertEqual([t.account_id for t in result.repeated], [7, 12])
        self.assertEqual(len(result.fingerprint), 64)

    def test_same_content_same_fingerprint(self):
        a = read_transactions(self.write(b"id_cuenta\n7\n"), "id_cuenta").fingerprint
        b = read_transactions(self.write(b"id_cuenta\n7\n"), "id_cuenta").fingerprint
        c = read_transactions(self.write(b"id_cuenta\n8\n"), "id_cuenta").fingerprint
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_excel_bom_and_windows_line_endings(self):
        result = read_transactions(self.write(b"\xef\xbb\xbfid_cuenta\r\n7\r\n12\r\n"), "id_cuenta")
        self.assertEqual([t.account_id for t in result.transactions], [7, 12])

    def test_header_ignores_case_and_spaces(self):
        result = read_transactions(self.write(b" ID_Cuenta \n7\n"), "id_cuenta")
        self.assertEqual(result.valid[0].account_id, 7)

    def test_column_in_other_position_and_short_rows(self):
        result = read_transactions(self.write(b"fecha,id_cuenta\n2026-10-22,7\n2026-10-22\n"), "id_cuenta")
        self.assertEqual([(t.account_id, t.invalid_code) for t in result.transactions], [(7, None), (None, "LINEA_VACIA")])

    def test_leading_zeros_count_as_repeated(self):
        result = read_transactions(self.write(b"id_cuenta\n7\n007\n"), "id_cuenta")
        self.assertEqual(len(result.transactions), 1)
        self.assertEqual(result.transactions[0].lines, [2, 3])

    def test_only_header_has_no_transactions(self):
        result = read_transactions(self.write(b"id_cuenta\n"), "id_cuenta")
        self.assertEqual(result.transactions, [])
        self.assertEqual(result.total_lines, 0)

    def test_missing_file_stops(self):
        with self.assertRaises(SystemException) as ctx:
            read_transactions(self.dir / "no_existe.csv", "id_cuenta")
        self.assertEqual(ctx.exception.codigo, "ENTRADA_NO_EXISTE")

    def test_missing_column_stops(self):
        with self.assertRaises(SystemException) as ctx:
            read_transactions(self.write(b"cuenta\n7\n"), "id_cuenta")
        self.assertEqual(ctx.exception.codigo, "ENTRADA_SIN_COLUMNA")

    def test_empty_file_stops(self):
        with self.assertRaises(SystemException) as ctx:
            read_transactions(self.write(b""), "id_cuenta")
        self.assertEqual(ctx.exception.codigo, "ENTRADA_SIN_COLUMNA")

    def test_not_utf8_stops(self):
        with self.assertRaises(SystemException) as ctx:
            read_transactions(self.write("id_cuenta\nñ\n".encode("cp1252")), "id_cuenta")
        self.assertEqual(ctx.exception.codigo, "ENTRADA_ILEGIBLE")


if __name__ == "__main__":
    unittest.main()
