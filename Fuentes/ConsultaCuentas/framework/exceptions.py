"""Excepciones del proceso, con el mismo reparto del REFramework.

- BusinessRuleException: resultado de negocio (la cuenta no existe, el dato no es
  válido). No se reintenta.
- SystemException: error técnico (red, tiempo de espera, error del sistema,
  configuración). Se reintenta según la librería y, si se agota, queda pendiente.

`codigo` es la clave del catálogo de observaciones de config.json o un código
técnico del log; el texto natural sale del catálogo, no de la excepción.
`intentos` dice cuántas veces se llamó al sistema antes de lanzarla (0 si no se llamó).
"""


class BusinessRuleException(Exception):
    def __init__(self, codigo: str, detalle: str = "", intentos: int = 0) -> None:
        super().__init__(detalle or codigo)
        self.codigo = codigo
        self.intentos = intentos


class SystemException(Exception):
    def __init__(self, codigo: str, detalle: str = "", intentos: int = 0) -> None:
        super().__init__(detalle or codigo)
        self.codigo = codigo
        self.intentos = intentos
