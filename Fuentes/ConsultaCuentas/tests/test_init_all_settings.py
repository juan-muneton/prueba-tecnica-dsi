"""Arnés del paso 1: config.json e InitAllSettings. Sin red.

Ejecutar desde Fuentes/ConsultaCuentas:  python -m unittest discover -s tests -t .
"""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

from framework.exceptions import SystemException
from framework.init_all_settings import (
    DEFAULT_CONFIG_PATH,
    LOGGER,
    REQUIRED_OBSERVATIONS,
    configure_log,
    init_all_settings,
    load_config,
)

REAL_CONFIG = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
SOURCES_DIR = Path(__file__).resolve().parents[1]


class InitAllSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "Configuracion").mkdir()
        self.config_path = self.root / "Configuracion" / "config.json"

    def tearDown(self):
        # En Windows el log abierto bloquea el borrado de la carpeta temporal
        for handler in list(LOGGER.handlers):
            LOGGER.removeHandler(handler)
            handler.close()
        self.tmp.cleanup()

    def write_config(self, change=None):
        data = copy.deepcopy(REAL_CONFIG)
        if change:
            change(data)
        self.config_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return self.config_path

    def assert_config_error(self, change, text):
        with self.assertRaises(SystemException) as ctx:
            load_config(self.write_config(change))
        self.assertEqual(ctx.exception.codigo, "CONFIG_INVALIDA")
        self.assertIn(text, str(ctx.exception))

    def test_real_config_loads(self):
        config = load_config(DEFAULT_CONFIG_PATH)
        self.assertEqual(config["ColumnaReferencia"], "id_cuenta")
        self.assertEqual(config["EstadoNegocio"], "Regla de Negocio")
        self.assertEqual(config["CodigosReintentables"], [408, 429, 500, 502, 503, 504])
        self.assertTrue(set(REQUIRED_OBSERVATIONS) <= set(config["Observaciones"]))
        self.assertTrue(config["ArchivoEntrada"].is_file())

    def test_relative_paths_resolve_from_project_root_not_cwd(self):
        path = self.write_config()
        previous = os.getcwd()
        os.chdir(tempfile.gettempdir())
        try:
            config = load_config(path)
        finally:
            os.chdir(previous)
        self.assertEqual(config["ArchivoEntrada"], (self.root / "Funcional/Input/cuentas.csv").resolve())
        self.assertEqual(config["RaizProyecto"], self.root.resolve())

    def test_missing_key_stops(self):
        self.assert_config_error(lambda d: d["Settings"].pop("ApiUrlBase"), "Settings.ApiUrlBase")

    def test_wrong_type_stops(self):
        def change(d):
            d["Settings"]["MaxIntentos"]["Valor"] = "4"
        self.assert_config_error(change, "Settings.MaxIntentos")

    def test_bool_is_not_a_number(self):
        def change(d):
            d["Settings"]["MaxIntentos"]["Valor"] = True
        self.assert_config_error(change, "Settings.MaxIntentos")

    def test_route_without_id_stops(self):
        def change(d):
            d["Settings"]["ApiRutaConsulta"]["Valor"] = "/posts/"
        self.assert_config_error(change, "{id}")

    def test_missing_observation_stops(self):
        self.assert_config_error(
            lambda d: d["Constants"]["Observaciones"]["Valor"].pop("TIMEOUT"), "TIMEOUT"
        )

    def test_repeated_key_between_sheets_stops(self):
        def change(d):
            d["Constants"]["NivelLog"] = {"Valor": "INFO", "Descripcion": ""}
        self.assert_config_error(change, "NivelLog")

    def test_invalid_json_reports_line(self):
        self.config_path.write_text('{\n  "Settings": {,\n}', encoding="utf-8")
        with self.assertRaises(SystemException) as ctx:
            load_config(self.config_path)
        self.assertIn("línea 2", str(ctx.exception))

    def test_init_creates_folders_and_daily_log(self):
        config = init_all_settings(self.write_config())
        for name in ("CarpetaOutput", "CarpetaCola", "CarpetaLogs"):
            self.assertTrue(config[name].is_dir(), name)
        log_path = config["CarpetaLogs"] / f"ConsultaCuentas_{date.today().isoformat()}.log"
        for handler in LOGGER.handlers:
            handler.flush()
        self.assertIn("INFO Configuración cargada; archivo=config.json", log_path.read_text(encoding="utf-8"))

    def test_screen_output_redirected_keeps_accents(self):
        # Como lo lanza el Programador de tareas: la pantalla va a una tubería
        path = self.write_config()
        code = "import sys; from framework.init_all_settings import init_all_settings; init_all_settings(sys.argv[1])"
        result = subprocess.run(
            [sys.executable, "-c", code, str(path)],
            cwd=SOURCES_DIR,
            capture_output=True,
            check=True,
        )
        self.assertIn("INFO Configuración cargada", result.stdout.decode("utf-8"))

    def test_log_file_name_uses_given_day(self):
        config = load_config(self.write_config())
        config["CarpetaLogs"].mkdir(parents=True)
        path = configure_log(config, today=date(2026, 10, 22))
        self.assertEqual(path.name, "ConsultaCuentas_2026-10-22.log")


if __name__ == "__main__":
    unittest.main()
