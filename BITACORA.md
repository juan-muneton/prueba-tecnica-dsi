# Bitácora — Reto técnico RPA Developer, DSI Factory

Cómo usé la IA para construir el proceso descrito en el [README](README.md).

## 1. Qué herramienta de IA usé y para qué

**Claude Code (Claude Opus 5.5)**, en la app de escritorio, trabajando directamente sobre los archivos del proyecto en mi computador.

- **Entender el reto:** leyó el enunciado directo de mi correo y el CSV, y consultó la API para ver cómo responde. Así salió que `abc` y `0` también devuelven 404: si no se validan antes, se confunden con cuentas que no existen.
- **Traer mi forma de trabajar:** le cargué como contexto mis guías de método y arquitectura (las *skills*: instrucciones que escribí a partir de mis proyectos de UiPath y que Claude Code lee antes de trabajar) y mis robots anteriores. Con eso aplicó al reto mi plantilla REFramework y mis buenas prácticas, en Python.
- **Plantear antes de programar:** propuso cada parte del diseño (entrada, errores y reintentos, cola, salida, configuración y log) y yo la aprobaba o la cambiaba. Todo quedó en `Documentacion/DECISIONES.md`.
- **Escribir el código y las pruebas:** paso por paso. 59 pruebas sin red y corridas reales contra la API: dos seguidas y con la red cortada.
- **Borrador del README y del runbook**, a partir de las decisiones; los comandos se verificaron corriéndolos.
- **Cómo lo controlé:** cada paso llegaba con sus pruebas y su corrida real; yo revisaba el resultado y no se pasaba al siguiente hasta aprobarlo.

## 2. Prompts que de verdad me sirvieron (copiados tal cual)

Trabajo conversando con la IA, casi siempre por voz. El peso no está en un prompt largo, sino en el contexto que le doy (mis guías de método y arquitectura y mis robots anteriores) y en dirigirla: plantear antes de programar, decidir cada parte y no dejar pasar errores. Estos son los mensajes que más cambiaron el resultado. Van tal cual; `[...]` marca un recorte y `[robot anterior]` reemplaza un nombre interno.

**1. Empezar por el final**
- *Qué buscaba:* que no programara nada sin saber qué había que entregar.
- *Mensaje:* «Porque primero, antes de construir cualquier cosa, de resolver cualquier problema, hay que primero entender qué debemos obtener de cada problema. [...] Hay que ver el final, hay que plantearlo bien, no vamos a arrancar por nada. Entonces, primero revisa cuáles son los entregables, qué hay que entregar.»
- *Qué cambió:* primero armamos la lista de entregables y esta bitácora, y se diseñó cada parte antes de escribir código.

**2. Darle mi contexto, no un prompt largo**
- *Qué buscaba:* que aplicara mi metodología y no una genérica.
- *Mensaje:* «Quiero que leas las skills de UiPath que yo tengo de desarrollo. Leas, por ejemplo, el proyecto, el último que hemos hecho, que es el del [robot anterior], las buenas prácticas, el uso del config, reintentos, plantilla de framework. [...] yo conozco solamente UiPath hasta ahora, entonces tú ayúdame a hacer ese acoplamiento de la mejor manera.»
- *Qué cambió:* el proyecto quedó con mi plantilla REFramework: Dispatcher, Process, SetTransactionStatus, Config, error de negocio y de sistema, y reintentos como en mis librerías.

**3. Hacer bien lo que se pide y explicar lo que no**
- *Qué buscaba:* no construir algo que el reto no pide, aunque yo lo use en mis robots.
- *Mensaje:* «si algo dejemoslo con una ausencia explicada no se realiza por que no lo pide, pero yo en mis robots prefiero tener un historico local adicional al de base de datos o reportes diarios por si algo falla»
- *Qué cambió:* el histórico no se construyó. Quedó explicado en el README, con cómo se haría sin duplicar.

## 3. Algo que la IA me entregó mal o incompleto, y cómo me di cuenta

- **Un formato de log difícil de leer.** Me propuso líneas hechas solo de pares (`id=7 http=200 intento=1 estado=Exitoso`), sacadas de una regla vieja de mis robots de UiPath. Me acordé de que en un robot anterior ya lo había cambiado porque así no se entendían. Le pedí comparar: la parte en UiPath de ese robot todavía usa ese formato, pero su parte en Python ya escribe primero una frase y después los datos. Quedó así: `Cuenta encontrada; id=7 codigo=CUENTA_ENCONTRADA intentos=1`.
- **Un defecto que quería dejar para después.** Entregó el paso 1 con todas las pruebas en verde, pero en la pantalla salía `Configuraci�n` (la «ó» dañada) y lo dejó anotado como "detalle" para pasar al paso 2. No lo acepté: el proceso corre desde el Programador de tareas, con la salida redirigida a un archivo, y ahí Windows usa otra codificación (cp1252) y daña las tildes. Lo corrigió y agregó una prueba que lanza el proceso con la salida redirigida.
  - **Y no lo corrigió completo:** solo arregló la salida normal. Al verificar los comandos del README apareció `secci�n` en el mensaje de configuración inválida, que sale por la salida de errores y que, justamente, no queda en el log. Se corrigió en las dos salidas, con su prueba.
- **Se adelantó.** Al inicio le pedí solo leer el contexto del reto y empezó a crear el proyecto y los archivos. Lo frené, borré todo y arrancamos por los entregables (prompt 1).
- **Una prueba que probaba mal.** Para simular el Excel abierto por otra persona, la prueba bloqueó la función de reemplazar archivos en todo el programa, y también rompió el guardado de la cola. Este no lo detecté yo: la prueba falló en la cola y no en el Excel, y la IA lo vio al leer el error y lo reportó. Se ajustó para que solo falle el `.xlsx`.

## 4. Qué decidí yo sin consultarle

- **El orden:** primero entender qué hay que entregar y diseñar cada parte; después programar. Y no pasar al siguiente paso con un defecto abierto.
- **Llevar esta bitácora desde el inicio**, para que los prompts quedaran copiados tal cual y no reconstruidos de memoria.
- **Usar mi plantilla de UiPath completa:** la estructura de carpetas de mis robots (`Configuracion`, `Fuentes`, `Funcional`, `Documentacion`) y los nombres del REFramework (`dispatcher`, `init_all_settings`, `process`, `set_transaction_status`, la librería del sistema, la cola), en vez de los nombres genéricos que propuso (`entrada`, `salida`, `estado`, `cliente_api`).
- **Estados y observaciones como en mis robots:** `Exitoso`, `Regla de Negocio` y `Error de Sistema`, con una `Observación` en lenguaje natural en vez de la columna "causa" que propuso.
- **Solo las columnas necesarias:** quité "Veces en archivo" porque repetía lo que ya dicen las líneas.
- **Dejar fuera el Excel histórico**, explicado en el README (prompt 3): el reto no lo pide, aunque en mis robots siempre dejo un histórico local además del reporte diario, por si algo falla.
- **Quitar del código y de la documentación los nombres internos de mis proyectos** (clientes, librerías y códigos de mis guías), porque ese trabajo es confidencial de mi empleador.
