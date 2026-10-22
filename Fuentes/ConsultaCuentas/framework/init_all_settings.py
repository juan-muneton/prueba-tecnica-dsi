"""InitAllSettings: lee config.json, valida lo obligatorio, prepara carpetas y el log.

Equivale a InitAllSettings.xaml: devuelve un diccionario de configuración que
viaja a las demás piezas (`Config("Clave")` en UiPath es `config["Clave"]` aquí).
Si falta algo obligatorio, se detiene antes de consultar nada.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Any

from framework.exceptions import SystemException

LOGGER = logging.getLogger("consulta_cuentas")

# Raíz del proyecto: Fuentes/ConsultaCuentas/framework/ -> tres niveles arriba.
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[3] / "Configuracion" / "config.json"

NUMBER = (int, float)
REQUIRED_SETTINGS: dict[str, type | tuple[type, ...]] = {
    "NombreProceso": str,
    "ArchivoEntrada": str,
    "ColumnaReferencia": str,
    "CarpetaOutput": str,
    "PrefijoOutput": str,
    "CarpetaCola": str,
    "CarpetaLogs": str,
    "NivelLog": str,
    "ApiUrlBase": str,
    "ApiRutaConsulta": str,
    "ApiTimeoutSegundos": NUMBER,
    "MaxIntentos": int,
    "EsperaInicialSegundos": NUMBER,
    "FactorEspera": NUMBER,
    "EsperaMaximaSegundos": NUMBER,
    "CodigosReintentables": list,
    "MaxConsecutiveSystemExceptions": int,
}
REQUIRED_CONSTANTS: dict[str, type] = {
    "EstadoExitoso": str,
    "EstadoNegocio": str,
    "EstadoSistema": str,
    "Observaciones": dict,
}
REQUIRED_OBSERVATIONS = (
    "CUENTA_ENCONTRADA",
    "CUENTA_NO_EXISTE",
    "VALOR_NO_NUMERICO",
    "LINEA_VACIA",
    "CUENTA_FUERA_DE_RANGO",
    "TIMEOUT",
    "SIN_CONEXION",
    "ERROR_HTTP",
    "RESPUESTA_INESPERADA",
    "ERROR_INTERNO",
    "PENDIENTE_POR_CORTE",
)
PATH_KEYS = ("ArchivoEntrada", "CarpetaOutput", "CarpetaCola", "CarpetaLogs")
FOLDER_KEYS = ("CarpetaOutput", "CarpetaCola", "CarpetaLogs")
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


def _fail(detalle: str) -> SystemException:
    return SystemException("CONFIG_INVALIDA", detalle)


def _read_sheet(data: dict[str, Any], sheet: str) -> dict[str, Any]:
    """Lee una sección (Settings o Constants) y devuelve solo los valores,
    como el cargador de UiPath que lee Name y Value e ignora Description."""
    section = data.get(sheet)
    if not isinstance(section, dict):
        raise _fail(f"Falta la sección '{sheet}' en config.json")
    values = {}
    for name, entry in section.items():
        if not isinstance(entry, dict) or "Valor" not in entry:
            raise _fail(f"'{sheet}.{name}' debe tener la forma {{\"Valor\": ..., \"Descripcion\": ...}}")
        values[name] = entry["Valor"]
    return values


def _check_types(values: dict[str, Any], required: dict[str, Any], sheet: str) -> None:
    for name, expected in required.items():
        if name not in values:
            raise _fail(f"Falta la clave obligatoria '{sheet}.{name}'")
        value = values[name]
        # bool es subclase de int en Python: True no puede pasar por un número
        if isinstance(value, bool) or not isinstance(value, expected):
            raise _fail(f"'{sheet}.{name}' tiene un tipo inválido: {type(value).__name__}")


def _check_values(config: dict[str, Any]) -> None:
    if config["MaxIntentos"] < 1:
        raise _fail("'MaxIntentos' debe ser 1 o más")
    if config["MaxConsecutiveSystemExceptions"] < 1:
        raise _fail("'MaxConsecutiveSystemExceptions' debe ser 1 o más")
    for name in ("ApiTimeoutSegundos", "EsperaMaximaSegundos"):
        if config[name] <= 0:
            raise _fail(f"'{name}' debe ser mayor que cero")
    if config["EsperaInicialSegundos"] < 0 or config["FactorEspera"] < 1:
        raise _fail("'EsperaInicialSegundos' no puede ser negativa y 'FactorEspera' debe ser 1 o más")
    if "{id}" not in config["ApiRutaConsulta"]:
        raise _fail("'ApiRutaConsulta' debe contener {id}")
    if config["NivelLog"].upper() not in LOG_LEVELS:
        raise _fail(f"'NivelLog' debe ser uno de {', '.join(LOG_LEVELS)}")
    if not all(isinstance(code, int) and not isinstance(code, bool) for code in config["CodigosReintentables"]):
        raise _fail("'CodigosReintentables' debe ser una lista de números")
    missing = [code for code in REQUIRED_OBSERVATIONS if not config["Observaciones"].get(code)]
    if missing:
        raise _fail(f"Faltan observaciones en el catálogo: {', '.join(missing)}")


def load_config(config_path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Carga Settings y Constants en un solo diccionario, valida y resuelve rutas.

    Las rutas relativas se resuelven desde la raíz del proyecto (la carpeta que
    contiene Configuracion), no desde donde se lance el proceso: el Programador
    de tareas de Windows arranca en otra carpeta.
    """
    config_path = Path(config_path).resolve()
    if not config_path.is_file():
        raise _fail(f"No existe el archivo de configuración: {config_path}")
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise _fail(f"config.json no es un JSON válido (línea {exc.lineno}, columna {exc.colno})") from exc

    settings = _read_sheet(data, "Settings")
    constants = _read_sheet(data, "Constants")
    repeated = settings.keys() & constants.keys()
    if repeated:
        raise _fail(f"Claves repetidas entre Settings y Constants: {', '.join(sorted(repeated))}")
    _check_types(settings, REQUIRED_SETTINGS, "Settings")
    _check_types(constants, REQUIRED_CONSTANTS, "Constants")

    config = {**settings, **constants}
    _check_values(config)

    root = config_path.parent.parent
    for name in PATH_KEYS:
        config[name] = (root / config[name]).resolve()
    config["RaizProyecto"] = root
    config["ArchivoConfig"] = config_path
    return config


def prepare_folders(config: dict[str, Any]) -> None:
    for name in FOLDER_KEYS:
        config[name].mkdir(parents=True, exist_ok=True)


def use_utf8_console() -> None:
    """Redirigida a un archivo o a una tubería (Programador de tareas), la pantalla
    de Windows usa cp1252 y las tildes salen dañadas: se fuerza UTF-8 en la salida
    normal y en la de errores (por donde sale un error de configuración)."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def configure_log(config: dict[str, Any], today: date | None = None) -> Path:
    """Un archivo de log por día en CarpetaLogs y lo mismo en pantalla.
    Formato de mis proyectos internos en Python: frase en español; después clave=valor."""
    today = today or date.today()
    log_path = config["CarpetaLogs"] / f"{config['NombreProceso']}_{today.isoformat()}.log"

    for handler in list(LOGGER.handlers):
        LOGGER.removeHandler(handler)
        handler.close()
    LOGGER.setLevel(config["NivelLog"].upper())
    LOGGER.propagate = False

    use_utf8_console()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    for handler in (logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler(sys.stdout)):
        handler.setFormatter(formatter)
        LOGGER.addHandler(handler)
    return log_path


def init_all_settings(config_path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    config = load_config(config_path)
    prepare_folders(config)
    log_path = configure_log(config)
    LOGGER.info(
        "Configuración cargada; archivo=%s log=%s",
        config["ArchivoConfig"].name,
        log_path.name,
    )
    return config
