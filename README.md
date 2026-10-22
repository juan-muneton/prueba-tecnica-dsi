# ConsultaCuentas — Reto técnico RPA Developer, DSI Factory

Proceso desatendido en Python que lee el CSV diario de cuentas médicas radicadas por una clínica, consulta cada cuenta en un sistema externo (`https://jsonplaceholder.typicode.com/posts/{id}`) y deja un Excel consolidado para que auditoría lo revise en la mañana.

Lo construí con la misma plantilla y las mismas buenas prácticas que uso en mis robots de UiPath (REFramework adaptado): configuración fuera del código, error de negocio separado del error de sistema, un solo dueño del reintento, una cola que no repite trabajo y trazabilidad por transacción. La [bitácora](BITACORA.md) cuenta cómo usé la IA y las decisiones detalladas están en [Documentacion/DECISIONES.md](Documentacion/DECISIONES.md).

## Qué hace

1. Lee `Funcional/Input/cuentas.csv` tal como llega, sin corregirlo a mano.
2. Valida cada línea: vacía, no numérica (`abc`) o menor que 1 (`0`) quedan como dato inválido y **no se consultan**. `"42"` se acepta como 42.
3. Junta los repetidos: cada número se consulta **una sola vez** (ver [Repetidos](#la-decisión-sobre-los-repetidos)).
4. Consulta cada cuenta con reintentos solo donde tiene sentido (ver [Frontera de reintentos](#frontera-de-reintentos)).
5. Guarda el resultado de cada cuenta en una cola del lote **después de cada consulta**: si se cae, al relanzarlo retoma donde quedó; si se corre dos veces, la segunda no vuelve a consultar lo resuelto.
6. Genera el Excel del día desde la cola (una fila por cuenta, sin duplicar nunca) y escribe al final del log un resumen por causa.

Con el CSV del reto: 21 líneas → 18 filas en el Excel (15 cuentas + 3 datos inválidos), 13 resueltas y 5 fallidas.

## Qué necesita instalado

- Python 3.10 o superior.
- Una librería: `openpyxl==3.1.5` (para el Excel). Las consultas HTTP usan solo la librería estándar (`urllib`).
- Salida a internet hacia `jsonplaceholder.typicode.com`.

## Cómo se ejecuta

```bash
cd Fuentes/ConsultaCuentas
python -m pip install -r requirements.txt
python main.py
```

- Se puede lanzar desde cualquier carpeta (`python Fuentes/ConsultaCuentas/main.py`): las rutas se calculan desde la raíz del proyecto, no desde donde se lanza. Así funciona igual desde el Programador de tareas de Windows o desde cron.
- Otra configuración: `python main.py --config RUTA/config.json`.
- Programado de madrugada (Programador de tareas): acción `python.exe` con el argumento `"<ruta>\Fuentes\ConsultaCuentas\main.py"`, y en la configuración de la tarea **"No iniciar una nueva instancia"** si la anterior sigue corriendo.

Pruebas (sin red, con una API falsa; 59 pruebas):

```bash
cd Fuentes/ConsultaCuentas
python -m unittest discover -s tests -t .
```

### Códigos de salida

| Código | Significado | Qué hacer |
|---|---|---|
| `0` | Todo resuelto (éxitos y reglas de negocio). | Nada. |
| `2` | Terminó, pero quedaron cuentas con `Error de Sistema`. Se reintentan en la siguiente ejecución. | Runbook, caso A. |
| `1` | El proceso se detuvo (configuración, archivo de entrada, cola o Excel). | Runbook, caso B. |

## Runbook: falló a las 3 a. m. y me llaman

**Relanzar siempre es seguro.** Las consultas son de solo lectura y la cola evita repetir lo ya resuelto; relanzar solo consulta lo pendiente y reconstruye el Excel sin duplicar.

**Dónde mirar:** `Funcional/Logs/ConsultaCuentas_<fecha>.log`. Las últimas líneas tienen el resumen; los problemas son las líneas `ERROR` y llevan `codigo=…`.

### Caso A — terminó con código 2 (quedaron errores de sistema)

Buscar las líneas `ERROR` con su `codigo=`:

| `codigo=` | Qué pasó | Qué hacer |
|---|---|---|
| `TIMEOUT`, `SIN_CONEXION`, `ERROR_HTTP` | La API o la red fallaron y se agotaron los 4 intentos. Si aparece `API caída, se detienen las consultas`, el proceso cortó a los 3 errores seguidos y dejó el resto pendiente. | Comprobar la API en un navegador: `https://jsonplaceholder.typicode.com/posts/1`. Si responde, relanzar. Si no responde, no hay nada que arreglar de nuestro lado: relanzar cuando vuelva. Auditoría ya ve esas cuentas marcadas en el Excel. |
| `RESPUESTA_INESPERADA` con `detalle=http=400/401/403` | La API rechaza la consulta: es configuración o permisos, no se reintenta porque reintentar no lo arregla. | Revisar `ApiUrlBase` y `ApiRutaConsulta` en `Configuracion/config.json`. |
| `RESPUESTA_INESPERADA` con `detalle=http=200 cuerpo ilegible` | Respondió algo que no es la cuenta (p. ej. una página intermedia de un proxy). | Relanzar. Si se repite, revisar la red (proxy, firewall). |
| `ERROR_INTERNO` | Falla del propio programa; el `detalle=` dice el tipo de error. | Relanzar una vez. Si se repite, escalar con el log. |

### Caso B — se detuvo con código 1

Buscar `Proceso detenido; codigo=…` en el log:

| `codigo=` | Qué pasó | Qué hacer |
|---|---|---|
| `CONFIG_INVALIDA` | `config.json` tiene un error. **Este no queda en el log** (sin configuración no hay log): sale por la pantalla. | Correr `python main.py` a mano: el mensaje dice qué clave falta o está mal. Corregir y relanzar. |
| `ENTRADA_NO_EXISTE` | No llegó el archivo de la clínica. | Revisar `Funcional/Input/`; pedir el archivo a la clínica y relanzar. |
| `ENTRADA_SIN_COLUMNA`, `ENTRADA_ILEGIBLE` | El archivo cambió de formato (no trae `id_cuenta` o no está en UTF-8). | No corregirlo a mano. Confirmar con la clínica; si la columna cambió de nombre, ajustar `ColumnaReferencia`. |
| `EXCEL_BLOQUEADO` | Alguien tiene abierto el Excel del día. | Pedir que lo cierren y relanzar: la cola quedó guardada y no se vuelve a consultar nada. |
| `COLA_ILEGIBLE` | El archivo de la cola (`Funcional/Cola/cola_<huella>.json`) se dañó o se editó a mano. | Moverlo a otra carpeta (no borrarlo, sirve para revisar) y relanzar: se vuelven a consultar las cuentas de ese lote. |
| `Proceso detenido por un error interno` | Falla inesperada; el log trae la traza. | Relanzar una vez. Si se repite, escalar con el log. |

## Frontera de reintentos

La librería del sistema (`libs/jsonplaceholder_lib.py`) es la **única dueña del reintento**: nadie la envuelve en otro bucle.

| Respuesta | ¿Reintenta? | Resultado | Por qué |
|---|---|---|---|
| Dato inválido (`abc`, vacío, `0`) | No se consulta | Regla de Negocio | Nunca va a cambiar. |
| 200 con la cuenta | — | Exitoso | |
| 404 | **No** | Regla de Negocio | La cuenta no existe; preguntar otra vez da lo mismo. |
| Timeout, sin conexión | Sí | Error de Sistema si se agota | Falla pasajera de red. |
| 408, 429, 500, 502, 503, 504 | Sí | Error de Sistema si se agota | El sistema está ocupado o caído un momento. |
| Otro 4xx (400, 401, 403…) | **No** | Error de Sistema | Es configuración o permisos: reintentar no lo arregla, hay que revisarlo. |
| 200 que no se puede leer | Sí | Error de Sistema si se agota | Suele ser una página intermedia pasajera. |

- 4 intentos en total, con espera creciente de 1, 2 y 4 s y ±10 % al azar. Si el sistema manda `Retry-After` (típico del 429), se respeta con un tope de 30 s. Tiempo máximo por consulta: 10 s.
- Si se agotan, la cuenta queda **pendiente** y la siguiente ejecución la vuelve a intentar.
- Si 3 cuentas seguidas terminan en Error de Sistema, el proceso deja de consultar: la API está caída y seguir solo alarga la corrida. Es el mismo criterio de `MaxConsecutiveSystemExceptions` del REFramework.

**Dónde puse la frontera y por qué:** se reintenta lo que depende del momento (red, saturación, caídas cortas) y no se reintenta lo que depende del dato o de la configuración (404, 4xx, valores inválidos), porque la respuesta sería la misma y solo se gastaría tiempo y carga del sistema.

## La decisión sobre los repetidos

**Decidí consultar cada número una sola vez y dejar una sola fila por cuenta, con la columna `Líneas` que dice en qué líneas vino** (el 7: `2, 6, 18`).

- Consultar dos veces el mismo número da el mismo resultado: repetirlo solo gasta llamadas.
- Es coherente con la re-ejecución: no duplicar filas.
- El repetido no se esconde: auditoría ve que la cuenta vino varias veces (posible doble radicación) y decide. Quitarlo en silencio sería perder esa señal.
- `007` se toma como la cuenta 7 (la API usa números) y cuenta como repetido.

## El Excel de salida

`Funcional/Output/resultado_cuentas_<fecha>.xlsx`, uno por lote. Si el mismo día llega otro archivo distinto, el suyo lleva `_2`.

| Columna | Qué trae |
|---|---|
| ID Cuenta | El valor tal como llegó (`7`, `abc`, vacío, `0`). |
| Líneas | En qué líneas del CSV vino. |
| User ID, Título, Contenido | El resultado de la consulta (`userId`, `title`, `body`). |
| Fecha de consulta | Cuándo se consultó; en una re-ejecución conserva la original. |
| Estado | `Exitoso`, `Regla de Negocio` o `Error de Sistema`. |
| Observación | Texto fijo del catálogo en `config.json`, en lenguaje natural. |

## Configuración

Todo parámetro vive en `Configuracion/config.json`, con dos secciones como el libro de configuración de mis robots: `Settings` (rutas, API, reintentos, nivel de log) y `Constants` (estados y catálogo de observaciones). Cada clave tiene `Valor` y `Descripcion`; el programa lee solo `Valor`. Al iniciar se valida todo lo obligatorio y, si algo falta o tiene un tipo inválido, el proceso se detiene antes de consultar nada.

## Cómo está organizado

Misma estructura de carpetas de mis robots y nombres de la plantilla REFramework:

```
Configuracion/config.json             Config-P###.xlsx
Fuentes/ConsultaCuentas/
  main.py                             Main.xaml: Init → Get → Process → Set → End
  framework/init_all_settings.py      InitAllSettings: carga y valida la configuración, carpetas y log
  framework/transaction_queue.py      La cola del lote (lo resuelto y lo pendiente); GetTransactionData
  framework/set_transaction_status.py SetTransactionStatus: clasifica, guarda en la cola, una línea de log
  framework/end_process.py            End: Excel diario y resumen
  framework/exceptions.py             BusinessRuleException / SystemException
  interactions/dispatcher.py          Dispatcher: lee y valida el CSV, junta repetidos (solo lee)
  business_process/process.py         Process: una transacción
  libs/jsonplaceholder_lib.py         Librería del sistema (como mis librerías de UiPath): consulta y reintentos
  tests/                              Arneses de prueba sin red
Funcional/Input · Output · Cola · Logs  Entrada, Excel, cola del lote y log diario
Documentacion/DECISIONES.md           Decisiones del planteamiento
```

El log sigue el formato de mis procesos en Python: primero una frase que dice qué pasó y después los datos (`Cuenta encontrada; id=7 codigo=CUENTA_ENCONTRADA intentos=1`).

## Lo que no hice, y por qué

- **Excel histórico acumulado.** En mis robots dejo, además del reporte diario y de la base de datos, un histórico local por si algo falla. No lo hice porque el reto no lo pide. Se haría sin duplicar con una columna `Lote` (fecha + huella del archivo): en cada corrida se borran las filas de ese lote y se reescriben desde la cola.
- **Bloqueo contra dos ejecuciones al mismo tiempo.** No está en el código; lo cubre la opción del Programador de tareas "No iniciar una nueva instancia". Dos corridas a la vez no dañarían datos de la API (solo se lee), pero competirían por el archivo de la cola.
- **Correo de resumen.** En mis robots el resumen también sale por correo; aquí queda en el log porque el reto no lo pide.
- **Retención de logs.** Un archivo por día, sin borrado automático.
- **A escala.** Cada cuenta es una transacción independiente y repetible, así que el mismo diseño pasa a una cola de mensajes (por ejemplo RabbitMQ) cambiando la cola en archivo por el broker, con varios consumidores en Docker. No lo construí: para un lote diario de este tamaño sería complejidad que no aporta.
