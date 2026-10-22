# Decisiones del proceso

Las decisiones que se tomaron antes de programar, parte por parte, y por qué. El [README](../README.md) resume lo esencial; aquí está el detalle. Los comentarios del código citan estas decisiones por su código (A1, B4, C3, D1…).

## Estructura del proyecto

Misma estructura de carpetas de mis robots de UiPath: configuración, fuentes, funcional y documentación separadas. Dentro de las fuentes, los nombres de mi plantilla REFramework en el formato de Python (minúsculas con guion bajo, PEP 8).

```
Prueba técnica DSI/                  raíz del repositorio
├── README.md · BITACORA.md          en la raíz, donde los busca quien revisa
├── Configuracion/config.json        Configuracion\Config-P###.xlsx en mis robots
├── Fuentes/ConsultaCuentas/         Fuentes\P### - Robot\ (el código)
├── Funcional/
│   ├── Input/cuentas.csv            el archivo de la clínica
│   ├── Output/                      Excel diario (D3, C4)
│   ├── Cola/                        estado de cada id (rama C); en UiPath lo guarda Orchestrator
│   └── Logs/                        log diario (E2); en UiPath lo guarda Orchestrator
└── Documentacion/DECISIONES.md      este archivo
```

- No hay `Funcional/Errores` ni `Funcional/Historico`: los errores van en el mismo Excel (D2) y el histórico es una ausencia explicada (C5).

Dentro de `Fuentes/ConsultaCuentas/`:

```
main.py                              Main.xaml (Init → Get → Process → Set → End)
requirements.txt                     dependencias (solo openpyxl), con versión exacta
framework/
  init_all_settings.py               InitAllSettings (lee y valida config.json, prepara carpetas y log)
  transaction_queue.py               La cola del lote: lo resuelto y lo pendiente; de aquí sale GetTransactionData
  set_transaction_status.py          SetTransactionStatus (clasifica, guarda en la cola, una línea de log)
  end_process.py                     End (Excel diario + resumen)
  exceptions.py                      BusinessRuleException (negocio) y SystemException (técnico)
interactions/
  dispatcher.py                      Dispatcher (lee el CSV, valida, junta repetidos; solo lee)
business_process/
  process.py                         Process (una transacción: consulta un id)
libs/
  jsonplaceholder_lib.py             Librería del sistema: encapsula la API y sus reintentos
tests/                               Arneses de prueba sin red
```

- `config.json` y `init_all_settings.py` van separados igual que en UiPath: el JSON es el dato (como el libro de configuración) y el `.py` es el código que lo lee y lo valida.
- La cola va dentro de `framework/` y no en una carpeta `queue/`, porque `queue` ya es un módulo de Python y chocaría.

## Rama A — Entrada

El CSV se lee tal como llega; no se corrige a mano. Es el Dispatcher: solo lee, valida y junta repetidos.

### A1. Fallas del archivo completo (detienen el proceso sin consultar nada)

| Caso | Código | Salida |
|---|---|---|
| El archivo no existe | `ENTRADA_NO_EXISTE` | 1 |
| No tiene la columna `id_cuenta` en el encabezado (o está vacío) | `ENTRADA_SIN_COLUMNA` | 1 |
| No está en UTF-8 | `ENTRADA_ILEGIBLE` | 1 |

- Se acepta el BOM que deja Excel al guardar y los saltos de línea de Windows. Las comillas (`"42"`) las quita el lector de CSV.

### A2. Reglas por línea, en este orden

| # | Regla | Ejemplo | Observación (D2) |
|---|---|---|---|
| 1 | Se quitan espacios y comillas sobrantes | ` "42" ` → `42` | — |
| 2 | Vacía | línea 12 | La línea está vacía. |
| 3 | No son solo dígitos | `abc`, `7.5`, `-3` | El valor no es un número de cuenta. |
| 4 | Menor que 1 | `0` | El número de cuenta debe ser mayor que cero. |
| 5 | Válida | `7`, `42` | se consulta |

- Ceros a la izquierda: `007` se toma como la cuenta `7` (la API usa números) y cuenta como repetido de `7`.

### A3. Repetidos y orden

- Un id que se repite se consulta una vez y en su fila se juntan todas sus líneas (D1).
- Las filas del Excel salen en el orden en que aparece cada id por primera vez en el archivo; los datos inválidos, en su posición.

### A4. Archivo sin cuentas

- Si solo trae el encabezado, no se llama a la API ni se genera Excel: se registra `Proceso terminado sin insumo` y termina con código 0.
- Si solo trae líneas inválidas, tampoco se llama a la API, pero sí se genera el Excel con ellas.

## Rama B — Errores y reintentos

### B1. La frontera: qué se reintenta

| Respuesta | ¿Reintenta? | Estado final | Por qué |
|---|---|---|---|
| Dato inválido (`abc`, vacío, `0`) | No se consulta | Regla de Negocio | Nunca va a cambiar; ni siquiera se llama a la API |
| 200 con datos | — | Exitoso | |
| 404 | No | Regla de Negocio | La cuenta no existe; preguntar otra vez da lo mismo |
| Timeout, sin conexión | Sí | Error de Sistema si se agotan | Falla pasajera de red |
| 408, 429, 500, 502, 503, 504 | Sí | Error de Sistema si se agotan | El sistema está ocupado o caído un momento |
| Otro 4xx (400, 401, 403) | No | Error de Sistema | Es configuración o permisos: reintentar no lo arregla; hay que revisarlo |
| 200 que no se puede leer | Sí | Error de Sistema si se agotan | Suele ser una página intermedia pasajera |

- La librería del sistema es la **única dueña del reintento**: quien la usa no la envuelve en otro bucle (dos capas de reintento multiplican las llamadas y esconden la causa).

### B2. Cuántas veces y cuánto espera (todo en la configuración)

- 4 intentos en total; espera creciente de 1, 2 y 4 segundos, con ±10 % al azar para no golpear al sistema todos a la vez.
- Si el sistema manda `Retry-After` (típico del 429), se respeta con un tope de 30 s. Si viene en formato de fecha, se usa la espera normal.
- Tiempo máximo por consulta: 10 s.

### B3. Si se agotan los intentos

- El id queda como `Error de Sistema` y **pendiente**: la siguiente ejecución lo vuelve a intentar (rama C). Equivale al reintento de la cola en mis robots.

### B4. Corte si el sistema está caído

- Si 3 ids seguidos terminan en `Error de Sistema`, el proceso deja de consultar el resto: la API está caída y seguir solo alarga la corrida. Los que faltan quedan pendientes y en el Excel con su propia observación (D2).
- Es el mismo criterio de `MaxConsecutiveSystemExceptions` del REFramework.
- El proceso termina con código de salida 2, para que el Programador de tareas lo marque y avise.

## Rama C — Re-ejecución y reanudación

Pedido: correrlo dos veces seguidas no vuelve a consultar lo resuelto ni duplica filas; si se cae a la mitad, al relanzarlo retoma donde quedó.

### C1. Una cola por lote, guardada después de cada id

- Archivo JSON en `Funcional/Cola/cola_<huella>.json` con el resultado de cada id consultado: estado, código de observación, datos, intentos y fecha de consulta.
- Se guarda **después de cada consulta**, escribiendo primero un temporal y reemplazando el archivo: una caída a mitad de escritura no lo daña. Si el proceso se cae, se pierde como mucho la consulta que estaba en curso.
- Por qué JSON y no una base de datos: es un lote diario pequeño, se abre con el Bloc de notas a las 3 a. m. y no necesita instalar nada. Si el volumen creciera, se cambia por SQLite o por una cola de mensajes.

### C2. Qué cuenta como resuelto

- Resuelto (no se vuelve a consultar): `Exitoso` y `Regla de Negocio`.
- Pendiente (se vuelve a intentar en la siguiente ejecución): `Error de Sistema` y los que no alcanzó a consultar.
- Los datos inválidos no se guardan en la cola: se vuelven a detectar al leer el CSV, sin llamar a la API.

### C3. El Excel se reconstruye completo en cada ejecución

- No se le agregan filas: se vuelve a generar entero desde la cola, una fila por id. Por eso nunca duplica.
- Se escribe en un temporal y luego se reemplaza. Si el Excel está abierto y bloqueado, el proceso se detiene con `EXCEL_BLOQUEADO` (salida 1); la cola queda intacta y basta con cerrarlo y relanzar.

### C4. A qué archivo pertenece la cola

- La cola se amarra a la **huella del contenido** del CSV (sha256). El mismo archivo relanzado retoma su cola; un archivo nuevo (el del día siguiente) empieza limpio, aunque se llame igual.
- Un Excel por lote, con la fecha del lote: `Funcional/Output/resultado_cuentas_2026-10-22.xlsx`. El nombre se fija la primera vez que corre el lote, para que una re-ejecución al día siguiente no cambie de archivo. Por qué no uno solo que acumule todo:
  - El enunciado lo plantea así: cada día llega un archivo y auditoría revisa el Excel de esa mañana.
  - Es lo que hago en mis robots: un Excel por fecha.
  - Un Excel no es una base de datos: si acumula, crece sin fin, un archivo dañado o bloqueado afecta todo el histórico, y no duplicar exigiría buscar y reemplazar filas de días anteriores.
  - El histórico consolidado, si se necesita, va a una base de datos o a un tablero, no a un Excel.
- Si llega un segundo archivo distinto el mismo día, su Excel lleva un sufijo (`_2`) para no pisar el primero.

### C5. Ausencia explicada: Excel histórico local (no se construye)

- No se hace porque el reto no lo pide.
- En mis robots sí lo uso: además del reporte diario y de la base de datos, dejo un histórico local acumulado por si algo falla en los otros destinos.
- Cómo se haría sin duplicar al re-ejecutar: columna `Lote` (fecha + huella del archivo); en cada corrida se borran las filas de ese lote y se vuelven a escribir desde la cola.

## Rama D — Salida

### D1. Una fila por id único

- Cada número de cuenta válido se consulta **una sola vez** y queda en **una sola fila** del Excel.
- La fila lleva la columna `Líneas` con las líneas del CSV donde vino; por ejemplo, el 7: `2, 6, 18`.
- Por qué:
  - Consultar dos veces el mismo número da el mismo resultado: repetirlo solo gasta llamadas.
  - Es lo que pide la re-ejecución: no duplicar filas.
  - El repetido no se esconde: auditoría ve que vino varias veces (posible doble radicación) y decide.
- Los datos que no son un número de cuenta (`abc`, línea vacía, `0`) van como filas aparte, con su valor original y su línea.

### D2. Estados y observación

- Columna `Estado` con los mismos tres valores de mis robots: **Exitoso**, **Regla de Negocio**, **Error de Sistema**.
- En vez de una columna de causa, una columna `Observación` en lenguaje natural, como en mis robots. El código técnico va solo al log.
- Cada observación es un **texto fijo del catálogo** en `config.json`, no en el código, para que el resumen pueda agrupar por ella. El detalle variable (el valor original, la línea) va en sus propias columnas.

| Estado | Observación | Cuándo |
|---|---|---|
| Exitoso | Cuenta encontrada. | 200 con datos |
| Regla de Negocio | La cuenta no existe en el sistema. | 404 (101, 150) |
| Regla de Negocio | El valor no es un número de cuenta. | `abc` |
| Regla de Negocio | La línea está vacía. | línea 12 |
| Regla de Negocio | El número de cuenta debe ser mayor que cero. | `0` |
| Error de Sistema | El sistema no respondió a tiempo; se agotaron los reintentos. | timeout |
| Error de Sistema | No hubo conexión con el sistema; se agotaron los reintentos. | red caída |
| Error de Sistema | El sistema respondió con error; se agotaron los reintentos. | 408, 429 o 5xx |
| Error de Sistema | Respuesta inesperada del sistema. | otro código o respuesta que no se puede leer |
| Error de Sistema | No se consultó porque el sistema estaba caído; se intentará en la siguiente ejecución. | ids que quedaron sin consultar por el corte de B4; sin esta fila, auditoría no sabría que faltan |
| Error de Sistema | Error interno del proceso; revisar el log. | un fallo del propio programa: como en el REFramework, todo lo que no es negocio es sistema |

### D3. Columnas

Criterio: solo lo que pide el enunciado ("el resultado de cada consulta") y lo que exige una decisión tomada. Mismo orden que en mis robots: negocio primero, `Estado` y `Observación` al final.

| # | Columna | Por qué está | Ejemplo |
|---|---|---|---|
| 1 | ID Cuenta | Identifica la fila; tal como llegó | `7` · `abc` · _(vacío)_ · `0` |
| 2 | Líneas | Hace visible la decisión de los repetidos (D1) | `2, 6, 18` |
| 3 | User ID | Resultado de la consulta (`userId`) | `1` |
| 4 | Título | Resultado de la consulta (`title`) | `magnam facilis autem` |
| 5 | Contenido | Resultado de la consulta (`body`) | _(texto)_ |
| 6 | Fecha de consulta | Muestra que una re-ejecución no volvió a consultar lo resuelto | `2026-10-22 10:57:33` |
| 7 | Estado | Catálogo de D2 | `Regla de Negocio` |
| 8 | Observación | Catálogo de D2 | `La cuenta no existe en el sistema.` |

- No hay columna de "veces en el archivo": repetiría lo que ya dicen las líneas.
- Una sola fecha en vez de inicio y fin: la duración de cada consulta no le sirve a auditoría (va al log).
- Las columnas 3 a 5 quedan vacías cuando no hay datos. Intentos y código técnico: solo en el log.
- La hoja se llama `Resultados`, con el encabezado fijo y filtros.

### D4. Resumen

Pedido: "cuántos resolvió, cuántos fallaron, agrupados por causa", al final de **cada ejecución**.

- Dónde: al final del log (y en pantalla). No en una hoja del Excel: el Excel es para auditoría y ya trae `Estado` y `Observación` para filtrar; el resumen es para quien opera el proceso.
- Resueltas = `Exitoso`. Fallidas = `Regla de Negocio` + `Error de Sistema`, agrupadas por `Observación`.
- Una línea dice cuántas se consultaron en esta ejecución y cuántas ya estaban resueltas: es la prueba de que la re-ejecución no repite.

Resumen real de la primera corrida con el CSV del reto:

```
===== RESUMEN DE LA EJECUCIÓN =====
Filas en el Excel: 18 (de 21 líneas del archivo)
Consultadas en esta ejecución: 15 · ya resueltas antes: 0
Resueltas: 13
Fallidas: 5
  Regla de Negocio · La cuenta no existe en el sistema.: 2
  Regla de Negocio · El número de cuenta debe ser mayor que cero.: 1
  Regla de Negocio · El valor no es un número de cuenta.: 1
  Regla de Negocio · La línea está vacía.: 1
```

## Rama E — Configuración y log

### E1. Configuración: `Configuracion/config.json`

Equivale al libro de configuración de mis robots, con sus dos hojas. Cada clave tiene `Valor` y `Descripcion`; el programa lee solo `Valor`, como el cargador de UiPath lee `Value` e ignora `Description`.

| Sección | Claves |
|---|---|
| `Settings` | `NombreProceso`, `ArchivoEntrada`, `ColumnaReferencia`, `CarpetaOutput`, `PrefijoOutput`, `CarpetaCola`, `CarpetaLogs`, `NivelLog`, `ApiUrlBase`, `ApiRutaConsulta`, `ApiTimeoutSegundos`, `MaxIntentos`, `EsperaInicialSegundos`, `FactorEspera`, `EsperaMaximaSegundos`, `CodigosReintentables`, `MaxConsecutiveSystemExceptions` |
| `Constants` | `EstadoExitoso`, `EstadoNegocio`, `EstadoSistema`, `Observaciones` (el catálogo de D2) |

- Las rutas relativas se resuelven desde la raíz del proyecto (la carpeta que contiene `Configuracion`), no desde donde se lance: el Programador de tareas de Windows arranca en otra carpeta.
- Al iniciar se valida todo lo obligatorio: que exista cada clave, su tipo, sus rangos, que la ruta tenga `{id}`, que el catálogo esté completo y que no haya claves repetidas entre las dos secciones. Si algo falla, se detiene antes de consultar nada con `CONFIG_INVALIDA` (salida 1) y un mensaje que dice qué clave revisar.
- Se puede pasar otro archivo con `--config` (por ejemplo, uno de pruebas).
- No hay secretos: la API es pública. Si los hubiera, irían en variables de entorno y no en el JSON.

### E2. Log

- Un archivo por día, `Funcional/Logs/ConsultaCuentas_2026-10-22.log`, y lo mismo en pantalla, en UTF-8 aunque la salida esté redirigida.
- Formato: **primero una frase corta en español que dice qué pasó, después `;` y los datos en `clave=valor`**. Se descartó un formato hecho solo de pares porque costaba leerlo.

Líneas reales de la corrida con el CSV del reto:

```
2026-10-22 10:57:32 INFO Archivo leído; archivo=cuentas.csv huella=1d2e22cf lineas=21 ids=15 repetidos=2 invalidas=3
2026-10-22 10:57:32 INFO Id repetido, se consulta una vez; id=7 lineas=2,6,18
2026-10-22 10:57:32 INFO Línea inválida, no se consulta; linea=9 valor='abc' codigo=VALOR_NO_NUMERICO
2026-10-22 10:57:32 INFO Cola abierta; cola=cola_1d2e22cfb558cafa.json pendientes=15 ya_resueltas=0
2026-10-22 10:57:33 INFO Cuenta encontrada; id=7 codigo=CUENTA_ENCONTRADA intentos=1
2026-10-22 10:57:34 INFO La cuenta no existe en el sistema; id=101 codigo=CUENTA_NO_EXISTE intentos=1
2026-10-22 10:57:36 INFO Excel generado; archivo=resultado_cuentas_2026-10-22.xlsx filas=18
```

Y con la API caída (de las pruebas):

```
WARNING Reintento; id=7 codigo=TIMEOUT detalle=TimeoutError intento=1 espera=1.0s
ERROR El sistema no respondió a tiempo; se agotaron los reintentos; id=7 codigo=TIMEOUT intentos=4 detalle=TimeoutError
ERROR API caída, se detienen las consultas; errores_seguidos=3 pendientes=12
```

- Qué se registra: el inicio, lo leído del archivo, la apertura de la cola (lo ya resuelto va ahí como una cantidad, no una línea por id), una línea por id consultado, cada reintento, cada error con su código técnico, el corte si la API está caída y el resumen final (D4).
- No se registran cuerpos HTTP completos: el código técnico (`codigo=`) basta para el runbook.
- Niveles: INFO para resultados, WARNING para reintentos, ERROR para `Error de Sistema` y fallas que detienen el proceso.
