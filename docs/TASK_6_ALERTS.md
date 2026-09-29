# Tarea 6 · Alertas de operaciones candidatas

> **Fase 3 del proyecto.** Depende de la 5.5 (ya cerrada) porque la Tarea 6
> alerta de **operaciones candidatas**, y una operación candidata es un patrón
> más una configuración que alguien ha validado fuera de muestra. Antes de la
> 5.5 esa configuración no existía, y alertar de un patrón suelto es avisar de
> señales que el backtest ya demostró que pierden.

---

## 1. Objetivo

Avisar por **Telegram** cuando se detecta un patrón que, combinado con una
configuración ya validada, constituye una **operación candidata** según los datos
disponibles — y **cada aviso apunta al run de backtesting que lo respalda**, con
su veredicto a la vista.

Canal principal: **Telegram**. Canal secundario: **WebSocket** para la pantalla en
vivo. **Email descartado**, y el motivo está en §2.3.

No es un sistema de ejecución. No abre posiciones. Es el paso anterior.

---

## 2. Decisiones de diseño, y por qué

### 2.1 Se alerta de una operación candidata, no de una señal de patrón

Es la decisión que el backlog (§7 de `BACKLOG_V2.md`) señalaba como *"la decisión
de diseño más importante de esa tarea"*, y aquí está resuelta con los datos delante
en vez de después.

Una señal de patrón aislada no vale nada, y la calibración lo dejó escrito: el
resultado depende más del nivel de stop y del régimen que del propio patrón. Un
MACD alcista con SL al 3% y `max_hold` de 4 velas no es la misma operación que un
MACD alcista con SL al 1,5% y 24 velas, y la primera se pierde de forma
sistemática.

Por tanto una alerta es la tupla **(patrón, dirección, configuración validada)**,
nunca el patrón solo.

### 2.2 Una alerta hereda el estatuto epistémico de su respaldo. Esta es la regla central

Un run de backtesting `completed` **no es evidencia de que la configuración
funcione**. Es un hecho de que la simulación terminó. La Tarea 5.5 costó tres
iteraciones demostrarlo, y el caso medido es el que manda: la combinación que
ganaba in-sample en los tres regímenes perdía frente a la original fuera de
muestra (+49,7% frente a +67,5% sobre el rango de 2022).

Si el sistema de alertas aceptara cualquier run `completed`, se convertiría en
una máquina de distribuir señales que el optimizador ya demostró que pierden,
usando como sello la palabra "backtesting". Eso es exactamente el fallo que el
proyecto lleva tres tareas evitando.

**Regla dura:** una regla de alerta solo se crea si su respaldo tiene un
veredicto **no descartado**:

| Veredicto del candidato | ¿Se puede crear la regla? | Por qué |
| --- | --- | --- |
| `sostenida` | Sí | Intervalo que excluye el cero y tres regímenes |
| `prometedora` | Sí, **con la advertencia visible en el mensaje** | Compatible con azar; se avisa, no se recomienda |
| `descartada` | **No.** 409 con el motivo | Ya se sabe que esa configuración pierde |

Y el mensaje de Telegram **lleva el veredicto y el IC95% dentro**, no un enlace
que hay que pulsar para saberlo. Un aviso que exige una segunda visita para saber
si fiarse de él es un aviso que se lee sin comprobar.

### 2.3 Email descartado

Un email es asíncrono, con bandeja de entrada, filtros de spam, y sin estado de
entrega que consultar sinstrumento. Para un aviso que llega mientras alguien
mira un gráfico y tiene que actuar en el momento, el email es el canal
equivocado: se lee en minutos, no en segundos. Telegram es síncrono, con
confirmación de entrega, y con un historial que ya se lee en el sitio donde se
recibe.

La contrapartida real de Telegram es que **no hay servidor de correo que auditar**,
y eso se acepta: la prueba queda en `alert_deliveries`, con el `message_id` que
devuelve la API y el error cuando no lo hay.

### 2.4 La alerta **no** puede decir el precio de entrada, y no lo dirá

La regla de entrada del motor es: la señal cierra en la vela `T` y la entrada es
la **apertura de `T+1`** (`entry_offset = 1`). En el momento en que se detecta el
patrón, `T+1` todavía no ha ocurrido, así que **el precio de entrada no se sabe**.

Lo mismo con los niveles: SL y TP son porcentajes *del precio de entrada*, así que
en dólares tampoco existen hasta que la entrada existe.

Un mensaje de Telegram que dijera "entrada 104.230" y fuera erróneo por tres
dólares sería peor que uno que no lo dijera, porque alguien operaría sobre él. Por
eso el mensaje lleva:

- **Precio de referencia**: el cierre de la vela `T`, etiquetado como tal.
- **Entrada**: "apertura de la vela siguiente", en texto, no en número.
- **SL y TP**: en porcentaje, calculados sobre la entrada futura.
- **Fórmula explícita** para que quien quiera pueda calcularlos: `entrada × (1 ± %)
  →  SL 102.665  TP 105.798`.

La alternativa, que es enviar un **segundo aviso** en `T+1` con los niveles ya
absolutos, es la V2 natural y se deja anotada. No en la V1: son dos avisos por
operación y el usuario tiene que aprender a emparejarlos.

### 2.5 Tres formas en que esto se convierte en una máquina de sobreajuste

Están aquí porque son las que se cierran con código, no con buena voluntad:

1. **Alertar de patrones sueltos** (§2.1).
2. **Reajustar la configuración con datos posteriores.** Una regla con SL al 1,5%
   que se "adapta" al mercado que viene es una configuración elegida con datos
   que ya no son fuera de muestra. La configuración de una regla es **inmutable**
   desde su creación; cambiarla es borrarla y crear otra, y queda registrado.
3. **Degradar el respaldo con el tiempo.** Una regla creada contra un candidato
   `sostenida` sigue respaldada por un informe de hace seis meses, en un mercado
   que ha cambiado. Por eso cada regla guarda `backing_age_days` y la pantalla lo
   enseña: **un respaldo envejecido se marca, no se borra**. El módulo 5.5 ya
   avisó de que el intervalo de confianza es una afirmación sobre un rango
   concreto; extenderlo a otro rango sin decirlo sería la misma mentira.

### 2.6 Lo que el módulo NO hace

- No opera. No abre ni cierra nada. FASE 4.
- No predice el precio objetivo con la misma confianza que el patrón. Dice que
  hay una configuración validada para ese tipo de señal, que es menos.
- No suaviza ni "interpreta" los datos. La alerta dice lo que el detector dijo.

---

## 3. Modelo de datos

Tres tablas, siguiendo la convención del resto del proyecto: `Numeric` para
dinero, JSONB para configuración congelada, `CASCADE` en la cadena de borrado.

### 3.1 `alert_rules` — la configuración

| Columna | Tipo | Nota |
| --- | --- | --- |
| `id` | UUID PK | |
| `name` | `String(80)` | Lo que el usuario llama a la regla |
| `symbol` / `timeframe` | `String(32)` / `String(8)` | |
| `pattern_name` | `String(64)` | Código del catálogo, FK lógica |
| `direction` | `String(10)` | `bullish` / `bearish` |
| `#: Configuración congelada, copiada del run que respalda` | | |
| `backtest_run_id` | UUID → `backtest_runs` | `CASCADE` |
| `walk_forward_run_id` | UUID → `walk_forward_runs` NULL | `SET NULL` |
| `candidate_rank` | `Integer` NULL | Qué candidata del informe es |
| `config` | JSONB | TP, SL, `max_hold`, `fee_bps`, `use_fraction`, `allow_short` |
| `#: Evidencia, congelada en la creación` | | |
| `backing_verdict` | `String(20)` | Copia del veredicto en ese momento |
| `backing_oi_low` / `backing_oi_high` | `Numeric(12,6)` NULL | IC95% en la creación |
| `backing_created_at` | `DateTime` | Para calcular la edad del respaldo |
| `#: Entrega` | | |
| `channel` | `String(20)` | `telegram` en la V1 |
| `enabled` | `Boolean` | |
| `cooldown_minutes` | `Integer` | Antigüedad mínima entre avisos (§4.4) |
| `min_confidence` | `Numeric(12,6)` NULL | Ver §4.2, se explica por qué |
| `last_alerted_at` | `DateTime` NULL | |
| `created_at` / `updated_at` | `DateTime` | |

**Por qué se copia el veredicto y el IC95% en vez de leerlos del candidato.**
Porque el informe es un artefacto histórico y la regla es una decisión presente.
Si el informe se recalculara, el IC cambiaría bajo una regla ya creada y la
evidencia de esa regla dejaría de ser la que el usuario miró al crearla. Copiarlo
con la fecha lo hace auditable.

**Por qué `walk_forward_run_id` es `SET NULL` y no `CASCADE`.** El respaldo de una
regla es evidencia acumulada. Que el usuario borre un informe no debe dejarlo sin
la regla, porque la regla ya se apoya en esa conclusión. Se queda con el
veredicto copiado y `walk_forward_run_id` en `NULL`, y la pantalla dice que el
informe se ha borrado.

### 3.2 `alerts` — cada aviso disparado

| Columna | Tipo | Nota |
| --- | --- | --- |
| `id` | UUID PK | |
| `rule_id` | UUID → `alert_rules` | `CASCADE` |
| `#: Identidad de la detección, que es lo que evita duplicados` | | |
| `signal_timestamp` | `DateTime` | Cierre de la vela `T` |
| `pattern_name` / `direction` | `String` | Redundante a propósito (§4.3) |
| `symbol` / `timeframe` | `String` | Idem |
| `reference_price` | `Numeric(20, 8)` | Cierre de `T`. **No** es la entrada |
| `detected_at` | `DateTime` | |
| `status` | `String(20)` | `pending` → `sent` / `failed` / `skipped` |
| `telegram_message_id` | `BigInteger` NULL | Lo que devuelve la API |
| `delivery_error` | `Text` NULL | |
| `attempts` | `Integer` | Intentos de entrega |
| `sent_at` | `DateTime` NULL | |

Índice **único** en `(rule_id, signal_timestamp)`. Es la garantía de que el mismo
patrón en la misma vela no genera dos avisos desde la misma regla, y sin eso
nada más importa (§4.3).

### 3.3 `alert_deliveries` — auditoría de la entrega

No es una tabla decorativa. Es la que responde *"¿llegó?"* cuando
alguien pregunte, y guarda lo que la API de Telegram devolvió. Sin ella, una
alerta fallida y una alerta nunca intentada se ven igual en la base: ambas son
filas que no están en Telegram.

| Columna | Tipo |
| --- | --- |
| `id` | UUID PK |
| `alert_id` | UUID → `alerts` `CASCADE` |
| `attempt` | `Integer` |
| `http_status` | `Integer` NULL |
| `response_body` | `Text` NULL |
| `attempted_at` | `DateTime` |

---

## 4. Los cinco problemas difíciles

### 4.1 La dependencia de features: el patrón no se puede detectar sin indicadores

El escáner de patrones (`patterns/scanner.py`) opera sobre un `DataFrame` que ya
tiene las columnas de features. El módulo de features las calcula y las persiste.

Una alerta en vivo necesita features **frescas** de las últimas velas, y hay dos
formas de conseguirlas:

- **A) Exigir un job de features reciente** y leer de ahí. Sencillo, pero acopla
  el ritmo de las alertas al del job de features, y si el usuario no lo relanza
  las alertas se_CALLAREn en silencio. El silencio por configuración ausente es
  el peor fallo posible en un sistema de avisos.
- **B) Calcular las features necesarias al vuelo** para una ventana pequeña
  (los últimos ~500 velas), con el mismo `FeatureService` que usa el job. Más
  trabajo por evaluación, y da autof suff iciencia.

**Se elige B, con A como caché**: si el job de features más reciente para ese
símbolo termina en las últimas N velas, se usa; si no, se calcula. Se prefiere la
ruta buena y se degrada a la correcta, y el motivo queda en el log de la
evaluación. Se acepta el coste porque una ventana de 500 velas por regla cada 5
minutos es del orden de mil operaciones, contra un trabajo de medio minuto.

Riesgo declarado: el camino B **debe** usar exactamente el mismo cálculo que el
job de features, o la alerta disparará sobre datos que el backtest nunca vio. Se
verifica con un test que compara la salida de B contra A sobre la misma ventana y
exige igualdad exacta, no aproximada.

### 4.2 La confianza del patrón no existe, y el campo `min_confidence` nace vacío

Sería natural añadir `min_confidence` al mensaje y un umbral en la regla. **No se
puede**, y hay que decirlo en la spec para que nadie lo añada después.

Los detectores son booleanos: `scan_macd_crossover` devuelve la vela donde la
línea cruza, sin ninguna probabilidad asociada. No hay un número que "sea la
confianza del patrón", y un número inventado en ese hueco es la forma más rápida
de convertir un detector en una bola de cristal con interfaz de usuario.

**Decisión:** `min_confidence` existe en el modelo, **nunca se rellena**, y su
docstring dice por qué. Si algún día el catálogo expone una confianza real, se
implementa el filtro en ese momento. Un filtro sobre una constante inventada es
peor que no tener filtro, porque da la sensación de estar filtrando.

### 4.3 Deduplicación: el `scan_job_id` no sirve como identidad

`pattern_occurrences` tiene PK `(timestamp, symbol, timeframe, pattern_name,
scan_job_id)`. Si se evaluan las reglas contra `pattern_occurrences`, la misma
detección en dos escaneos solapados es **dos filas** y por tanto **dos alertas**
para el mismo patrón en la misma vela.

Se evalúa, por tanto, contra la detección en vivo (§4.1) y no contra
`pattern_occurrences`. Y en la tabla `alerts` el índice único
`(rule_id, signal_timestamp)` es la red de seguridad: aunque dos reglas se
solapen en el tiempo, la misma regla nunca avisa dos veces de la misma vela.

`pattern_name` y `direction` están redundantes en `alerts` a propósito. Una
alerta es un registro histórico de lo que se detectó y de lo que se avisó; si la
regla se edita después, la alerta sigue diciendo la verdad de lo que ocurrió.

### 4.4 Anti-spam: cooldown y agregado

Un MACD sobre 1h puede disparar cada pocas velas. Telegram tiene límites (unos
30 mensajes por segundo global, **1 por segundo y por chat**) y, más importante,
un usuario que recibe 40 mensajes en una hora apaga el sistema y no vuelve a
encenderlo.

- **`cooldown_minutes`** por regla, con un valor por defecto de 60. Una regla no
  vuelve a avisar dentro de ese plazo aunque vuelva a dispararse.
- **Reintentos** con retroceso exponencial y un tope de 5 intentos. Telegram da
  `429` con `retry_after` cuando se pasa de 1 mensaje por segundo, y ese número
  **se respeta**: es el que dice la propia API, no uno inventado.
- **Límite duro de longitud**: 4096 caracteres, el máximo de Telegram. Un mensaje
  más largo se trunca por el final y se marca con `…` explícito, porque un
  mensaje cortado en mitad de un número es peor que no enviado.

### 4.5 El reloj y las zonas horarias

Toda la comparación de timestamps se hace en **UTC**, que es la convención del
proyecto y el motivo de que `load_candles` normalice. El mensaje de Telegram, en
cambio, se lee en hora local, y ahí es donde aparece el error clásico: un
`timestamp` escrito sin zona se lee como local en el servidor y como UTC en el
navegador, y las dos cosas difieren.

El mensaje incluye la hora de la vela **en UTC y con la zona explícita**, y la
aplicación muestra además la hora local del navegador. Si el usuario está en
`Europe/Madrid`, ve `10:00 UTC · 12:00` y sabe exactamente a qué vela corresponde.

---

## 5. El mensaje de Telegram

```
🟢 OPERACIÓN CANDIDATA · BTCUSDT

Cruce alcista de MACD
dirección: LONG

Vela          2026-07-15 10:00 UTC
referencia    104.230  (cierre de esa vela)
entrada       apertura de la vela siguiente

Configuración validada
  SL           -1,5%
  TP           sin objetivo
  máx. velas   24

Respaldo
  Veredicto    SOStenida
  IC95%        [+2,1 ; +48,7]%  (excluye el cero)
  Retorno OOS  +18,2%   Mercado +6,1%   Ventanas 9
  Informe      walk-forward 3a9c1f2e · candidato nº1

No es una recomendación. Es una configuración que, sobre datos que ya
viste, rindió esto. El intervalo no dice qué va a pasar mañana.
```

Decisiones de formato, y el motivo de cada una:

- **`parse_mode=HTML`** y no `MarkdownV2`. MarkdownV2 obliga a escapar 18
  caracteres (`_ * [ ] ( ) ~ > # + - = | { } . !`), y un `1.5` sin escapar rompe
  el mensaje entero. HTML necesita escapar `<`, `>` y `&`, que en este contenido
  no aparecen nunca. Es menos elegante y mucho menos frágil.
- **El veredicto y el IC95% van dentro del mensaje**, no en un enlace (§2.2).
- **El descargo final no es decorativo**: es la diferencia entre un aviso y una
  recomendación, y un mensaje que se puede reenviar a alguien sin contexto
  necesita llevárselo.
- **El precio se llama "referencia", nunca "entrada"** (§2.4).
- **El número de la run del respaldo va en el mensaje** para que la auditoría no
  dependa de la aplicación.

---

## 6. Configuración

```
# Telegram (Tarea 6)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
TELEGRAM_ENABLED=false
```

`TELEGRAM_ENABLED` existe para que el sistema **no pueda** enviar mensajes por
accidente en desarrollo o en los tests. Sin él, un `pytest` que_instance un
servicio de alertas con un token real mandaría avisos de operaciones al móvil de
quien lo escribiera, y ese es un fallo que no se deshace.

El `chat_id` **no se busca solo**: un bot no puede escribir a alguien que no le
haya escrito primero. El procedimiento es el del README, y es la causa número uno
de "las alertas no llegan":

1. Hablar con `@BotFather` y crear el bot. Devuelve el token.
2. Abrir el chat con el bot y enviar `/start`.
3. `GET https://api.telegram.org/bot<token>/getUpdates` → `chat.id`.
4. Pegarlo en el `.env`.

El token **no se versiona** y está en `.gitignore` con el resto de secretos. Si
se filtra, `@BotFather` lo revoca y genera uno nuevo.

---

## 7. API

| Método | Ruta | Qué hace |
| --- | --- | --- |
| `GET` | `/alerts/rules` | Lista las reglas con la edad de su respaldo |
| `POST` | `/alerts/rules` | Crea una regla. **409** si el respaldo está `descartada` |
| `PATCH` | `/alerts/rules/{id}` | Activa/desactiva. **No** cambia la configuración |
| `DELETE` | `/alerts/rules/{id}` | Borra la regla y sus avisos |
| `GET` | `/alerts` | Historial, paginado y filtrable |
| `GET` | `/alerts/{id}` | Una alerta con su entrega y su texto exacto enviado |
| `POST` | `/alerts/telegram/test` | Envía un mensaje de prueba. Valida token y `chat_id` |
| `GET` | `/alerts/evaluations` | Última evaluación por regla, con su motivo |
| `WS` | `/alerts/stream` | Alertas nuevas en vivo, para la pantalla |

El `PATCH` **no toca `config`** a propósito (§2.5-2). Cambiar los niveles de una
regla es crear otra regla, y que quede en el historial.

---

## 8. Plan de ejecución

| # | Bloque | Contenido | Riesgo |
| --- | --- | --- | --- |
| 1 | **Configuración y cliente Telegram** | `Settings`, cliente HTTP con reintentos y `retry_after`, test del cliente contra un doble | Bajo |
| 2 | **Modelos y migración** | Las tres tablas, el índice único, `CASCADE`/`SET NULL` bien puestos | Bajo |
| 3 | **Respaldo: la regla solo con veredicto** | Consulta que une run + candidato + veredicto, y el 409 con el motivo. **Test primero** | Medio |
| 4 | **Evaluación** | Features al vuelo (§4.1), detección, niveles, y el test de igualdad con la ruta del job | **Alto** |
| 5 | **Servicio y entrega** | Anti-spam, reintentos, truncado, escritura de la entrega | Medio |
| 6 | **Tarea periódica** | `beat_schedule`, evaluación de reglas, cancelación entre reglas | Medio |
| 7 | **Router** | Los ocho endpoints, con sus códigos | Bajo |
| 8 | **Tests de servicio** | El 409 del respaldo, la deduplicación, el anti-spam, el fallo de entrega que **no** se pierde | Medio |
| 9 | **Frontend** | Lista de reglas con la edad del respaldo, historial, y el aviso en vivo | Medio |
| 10 | **Verificación real** | Un escaneo en vivo, una alerta real a Telegram, y comprobar que el `message_id` existe | **Alto** |

**Estimación: 3,5 días.** Dos de backend y uno y medio de frontend, por el mismo
motivo que en la 5.5: el riesgo está en decidir *qué* avisar y *con qué
números*, no en las pantallas.

### El orden tiene una razón

El bloque 3 va antes que el 4 a propósito. La regla de "solo con veredicto no
descartado" es la que impide que el sistema distribute señales que el optimizador
ya probó que pierden, y es la que hay que tener probada **antes** de que exista
una sola línea que mande un mensaje. Si se construye el evaluador primero y la
guarda después, hay un momento en el que el sistema manda avisos sin respaldo
aceptado, y ese momento es el que no se puede deshacer.

### La verificación real, y qué se considera un éxito

No basta con que los tests passen. El éxito es:

1. Una detección real dispara una alerta real por Telegram.
2. El `telegram_message_id` de la API está en `alert_deliveries`.
3. El mismo patrón en la misma vela **no** genera un segundo aviso (§4.3).
4. Una regla respaldada por un candidato `descartada` **no se puede crear** (§2.2).
5. El mensaje dice "referencia" y no "entrada", y la diferencia se ve a simple vista.

El punto 4 se prueba con el `sostenida`/`prometedora` reales que dejó la 5.5, no
con un doble de test. Si un candidato real `descartada` no puede generar regla,
la cadena de evidencia está entera.

---

## 9. Riesgos

| Riesgo | Mitigación |
| --- | --- |
| Avisar de señales que pierden | Regla dura: solo respaldos no descartados (§2.2), y el veredicto dentro del mensaje |
| Duplicar alertas por escaneos solapados | Se evalúa contra detección en vivo, e índice único `(rule_id, signal_timestamp)` (§4.3) |
| Enviar un precio de entrada equivocado | El mensaje no da precio de entrada; da referencia y la fórmula (§2.4) |
| Features desfasadas y alertas mudas | Se calculan al vuelo y se registra el motivo de la ruta usada (§4.1) |
| Spam y usuario que apaga el sistema | `cooldown_minutes`, `retry_after` de la propia API, truncado explícito (§4.4) |
| Confianza de patrón inventada | `min_confidence` existe y nunca se rellena (§4.2) |
| Token filtrado | `.env` y `.gitignore`; `@BotFather` revoca |
| "Las alertas no llegan" | `POST /alerts/telegram/test` valida token y `chat_id` sin esperar una detección real (§7) |
| El respaldo envejece y la alerta no lo dice | `backing_created_at` y edad visible en pantalla y en el mensaje (§2.5-3) |

## 10. Fuera de alcance

- Ejecución automática de la operación. Es la FASE 4, y depende de que la FASE 3
  haya sobrevivido al papel.
- Niveles de precio absolutos en el mensaje. Requiere el segundo aviso en `T+1`.
- Alertas de patrones sin respaldo.
- Varios usuarios o varios `chat_id`. La V1 es de un usuario, que es quien
  escribe el código.
- Alertas de régimen: "ha cambiado el régimen" es un análisis distinto y no una
  alerta de ejecución.
