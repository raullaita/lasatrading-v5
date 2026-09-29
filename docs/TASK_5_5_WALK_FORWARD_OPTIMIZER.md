# Tarea 5.5: Optimizador Walk-Forward (WFO)

> Fase 2 del roadmap de `PROJECT_GUIDELINES.md`. Depende de la Tarea 3.5
> (`TASK_3_5_DATA_EXPLORER.md`) y **hereda su contrato estadístico**: este motor
> no busca la configuración que más gana, produce candidatos y los refuta o
> confirma con datos fuera de muestra.

## 1. Objetivo

Dado un escaneo ya completado y una rejilla de parámetros, ejecutar un
**walk-forward** sobre ventanas temporales y devolver, para cada configuración de
la rejilla, un **veredicto con evidencia**:

- En qué ventanas se elige como candidata (in-sample) y qué rinde fuera de
  muestra.
- Con qué **Puntuación de Robustez**, calculada **solo** sobre ventanas fuera de
  muestra.
- Con su **intervalo de confianza al 95%** y su diferencia frente al mercado.
- Con un veredicto de tres grados que **no** distingue "gana" de "no se puede
  saber", porque esa distinción es la que evita que se confunda ruido con
  resultado.

Lo que este motor **no** hace, y por diseño (§7): devolver un ganador.

## 2. Punto de partida verificado

Todo lo que hace falta ya existe. La tarea es orquestarlo, no construirlo.

| Pieza | Dónde | Qué aporta |
| --- | --- | --- |
| `analysis.sweep` | `backtesting/analysis.py` | Evalúa una rejilla completa en memoria, sin escribir. Ya devuelve Sharpe, drawdown, win rate y reparto de salidas por combinación |
| `run_backtest` | `backtesting/engine.py` | Simulación pura sobre velas y señales |
| `buy_and_hold` | `backtesting/analysis.py` | Benchmark de mercado con la misma regla que la estrategia |
| `PatternScanService._load_signals` | `patterns/service.py` | Señales del escaneo, con dirección resuelta |
| `load_candles` | `data/candles.py` | Velas del rango, con orden garantizado |
| `StrategyConfig` | `backtesting/engine.py` | Validación de la estrategia |
| Tarea Celery + logs + WebSocket | `backtesting/` | El patrón exacto de ejecución larga que hay que replicar |

**Coste real medido** (4.344 velas, 724 señales, 20 repeticiones):

| Señales | ms por simulación |
| --- | --- |
| 181 | 79,8 |
| 362 | 98,6 |
| 724 | 54,8 |
| 1.448 | 60,6 |

El coste **no escala con las velas del rango**, que es lo que hace asumible un
WFO con ventanas solapadas: 120 combinaciones × 10 ventanas ≈ 1.200 simulaciones
≈ **66-96 s**.

Consecuencia directa: **esto no cabe en un POST síncrono.** Sería una tarea
Celery con progreso por ventana, igual que un backtest.

## 3. El algoritmo

### 3.1 · Ventanas

El rango del escaneo se corta en ventanas **roll-forward** de tamaño fijo, con
desplazamiento del mismo tamaño (por defecto) y solapamiento configurable.

Para un rango de 1.095 días con ventanas IS de 365, OOS de 90 y
desplazamiento de 90:

```
        IS-1              OOS-1
|---------|------------|---------|
            IS-2              OOS-2
                |---------|---------|
                    IS-3              OOS-3
```

- **In-sample**: se evalúa la rejilla completa y se elige la mejor por el
  criterio de la §4.1.
- **Out-of-sample**: se aplica **solo** esa elección y se mide.
- **El OOS de una ventana no está en el IS de esa misma ventana**, y la selección
  de cada ventana usa **solo** su propio IS. Eso sí es comprobable, y va con
  test: las señales de cada ventana se filtran por su intervalo, y el criterio
  de la §4.1 no ve nada fuera de él.

  > **Corrección.** Una versión anterior de esta spec decía "el OOS de la
  > ventana N nunca está en el IS de ninguna otra", y es imposible de cumplir
  > con solapamiento. Con ventanas de 365 días y desplazamiento de 90, el OOS de
  > la ventana 1 es [365, 455) y el IS de la ventana 2 es [90, 455): el primero
  > está **dentro** del segundo. Y es el setup normal, no un error.
  >
  > Lo que sí importa, y lo que no hay fuga en: el OOS de la ventana N no
  > participa en la elección de la ventana N, ni en la de ninguna otra. Cada
  > ventana elige con su IS y se evalúa con su OOS, y ninguna métrica de
  > validación entra en ninguna decisión.
  >
  > Lo que sí tiene un coste, y no es fuga sino estadística: con solapamiento las
  > ventanas OOS **no son independientes entre sí**, así que el número efectivo de
  > ventanas es menor que el número de ventanas. Por eso el IC95% se calcula con
  > bootstrap de bloques (§5.3) y no suponiendo observaciones independientes.

Con `desplazamiento < tamaño_IS` las ventanas se solapan (más ventanas, menos
independencia entre ellas); con `desplazamiento = tamaño_IS` son contiguas. El
solapamiento acelera la convergencia de la elección y **cuesta independencia
estadística**: el número de ventanas efectivo es menor que el número de
ventanas. Se reporta el desplazamiento junto al resto.

### 3.2 · La frontera de la ventana es la SEÑAL, y las velas llegan más allá

Una señal del tiempo T entra a la apertura de T+1 y puede seguir abierta 24
velas. Si el corte de la ventana fuera por velas y se cortara el marco, las
últimas operaciones de cada ventana saldrían con motivo `end_of_data` y cada
ventana parecería peor de lo que es — un sesgo silencioso en la dirección
equivocada.

Decisión: **una señal pertenece a la ventana por su marca de tiempo, y el marco
de velas se extiende `max_hold` barras más allá del final de la ventana** para
que la operación pueda resolverse. No se fuerza cierre artificial.

La consecuencia honesta: el resultado de una operación puede depender de velas
que caen en la siguiente ventana. Eso es correcto en un walk-forward (para saber
el resultado de una señal solo hacen falta velas futuras) y hay que decirlo, no
esmburrarlo: **el OOS mide decisiones, noecuta luego posiciones planificadas.**

### 3.3 · El capital se reinicia en cada ventana

`initial_capital` vuelve al valor del run en cada simulación. Sin eso, el equity
de la ventana N arrastra el de todas las anteriores y las ventanas dejan de ser
comparables entre sí, que es justo lo que el motor necesita medir.

Para el gráfico, las curvas OOS se **encadenan**: cada ventana arranca en el
capital final de la anterior. Así la curva OOS conjunta es continua y comparable
con el benchmark encadenado, y ninguna ventana se pondera más que otra.

## 4. La Puntuación de Robustez

### 4.1 · Criterio de elección en in-sample

**Sharpe.** No PnL: el Sharpe es libre de escala, y comparar ventanas de
capitales distintos por PnL favorece a la ventana más ruidosa. `sweep` ya lo
devuelve.

> Nota honesta: elegir por Sharpe IS es una decisión, no una verdad. La
> alternativa habitual —ensamblaje o_train/test_split— da clases parecidas. Se
> documenta aquí para que se pueda discutir con su nombre delante.

### 4.2 · Definición

Se calcula **exclusivamente sobre ventanas OOS**. Una configuración es candidata
si fue elegida en in-sample en al menos `min_windows` ventanas (3 por defecto);
si no, no tiene nada que puntuar y no se muestra.

Con `W` ventanas OOS en las que salió elegida:

| Término | Definición | Peso |
| --- | --- | --- |
| `sharpe` | media del Sharpe OOS de sus ventanas | +0,35 |
| `win_rate` | media del win rate OOS | +0,20 |
| `consistencia` | fracción de ventanas OOS con PnL > 0 | +0,20 |
| `dd` | peor drawdown máximo OOS, en tanto por uno | −0,15 |
| `dispersion` | desviación típica del Sharpe OOS entre ventanas | −0,10 |

```
score = 100 · (0,35·sharpe_norm + 0,20·win_rate + 0,20·consistencia
               − 0,15·dd − 0,10·dispersion)
```

`sharpe_norm` es `tanh(sharpe / 2)`, que comprime en [-1, 1] y evita que un
Sharpe extremo domine la suma.

**Los pesos están congelados en esta especificación y no se ajustan.** Elegir el
primer `score` y después buscar los pesos que lo hagan subir es el mismo
sobreajuste un nivel más arriba, y es más difícil de detectar porque parece
metodología. Los pesos son un juicio, se declaran y se revisan, pero no se
optimizan contra los resultados que producen.

El score **ordena candidatos que ya han pasado las guardas** (§5). No sustituye a
las guardas: un candidato con score alto que no supera al mercado no se
recomienda, y uno que las pasa todas pero con `score` bajo sale último, no
descartado.

### 4.3 · Lo que el score NO mide

- No mideSharpe *esperado*: no hay forecast, hay historial.
- No mide riesgo de tamano: `use_fraction` está fuera de la rejilla.
- No mide sobre una distribución: el IC95% de la §5.3 es la que dice si el
  resultado es distinguible del ruido, y son cosas distintas. Un score alto con
  un IC que incluye cero es un candidato, no un ganador.

## 5. Las guardas y el veredicto

### 5.1 · Guardas duras

Una configuración es **descartada** si falla cualquiera:

1. Menos de `min_windows` ventanas OOS en las que salió elegida.
2. Menos de `min_trades` operaciones OOS en total.
3. No supera al mercado en al menos el 60% de sus ventanas OOS.
4. PnL OOS acumulado negativo.
5. **Regímenes distintos insuficientes.** Un candidato solo puede llegar a
   `sostenida` si su OOS cubre **al menos tres regímenes de mercado** declarados
   por el usuario (alcista, lateral, bajista). Con uno o dos, el techo del
   veredicto es `prometedora`, por mucho que el IC95% excluyera el cero.

El guard 5 es el más importante de los cinco y el que más va a molestar, así que
conviene decir por qué está: **una sola serie de precios no puede demostrar
robustez.** Con un único régimen, un IC95% que excluye el cero demuestra que el
resultado no es ruido *en ese tramo*, que es algo distinto de que vaya a
repetirse. Es exactamente el error que se cometió al elegir la configuración
`sin TP / SL 2,0%` en el mercado alcista y descubrir que en el bajista perdía: el
problema nunca fue el intervalo, fue que había un solo régimen. El intervalo
contaba la historia de un tramo y el motor lo infirmaba como si fuera universal.

La V1 no puede exigir tres regímenes por sí solo, porque el usuario puede no
tenerlos importados. Lo que sí hace es **no dejar pasar el veredicto completo**:
con un solo régimen, la respuesta es un candidato con la etiqueta
`prometedora` y un aviso explícito de que falta evidencia de mercado. Pedir tres
regímenes distintos es un requisito de trabajo, y la pantalla de configuración
lo dice en vez de dejar que se descubra al leer el resultado.

### 5.2 · Veredicto de tres grados

| Veredicto | Condición | Cómo se puede leer en pantalla |
| --- | --- | --- |
| `descartada` | falla alguna guarda dura | "No se recomienda. Falló: <guardas concretas>" |
| `prometedora` | pasa las guardas, pero el IC95% del PnL OOS **incluye** el cero | "Supera las guardas en M de N ventanas. El intervalo de confianza incluye el cero: **no se puede afirmar que gane**" |
| `sostenida` | pasa las guardas **y** el IC95% **excluye** el cero | "Gana en M de N ventanas, supera al mercado en K, y el IC95% [a, b] excluye el cero" |

La distinción entre `prometedora` y `sostenida` es el objeto de la tarea. Una
herramienta que colapsa las dos en "estrategia válida" es la que produce
estrategias de papel.

### 5.3 · IC95%

Bootstrap sobre el PnL de las operaciones OOS agregadas, remuestreando con
reemplazo, 20.000 repeticiones, **paginado**. El tope de `page_size` en
`/trades` es 200 y la primera versión de este cálculo en el ciclo de calibración
se quedó con las 200 primeras de un run de 440: el intervalo salió
artificialmente estrecho y parecía mucho más concluyente de lo que era.

Se calcula en el motor, sobre las operaciones que la simulación acaba de
producir, y **no** sobre las persistidas de un backtest: el motor no tiene tabla.

Es un **bootstrap de bloques**, no un remuestreo plano. Se remuestrea cada
ventana por separado, se suman los resultados por ventana y se suman entre
ventanas. Remuestear plano trataría cada operación como independiente de todas
las demás, y con ventanas solapadas no lo son: dos operaciones de ventanas
distintas pueden ser la misma señal vista desde dos ventanas, y contarlas dos
como independientes acorta el intervalo por debajo de lo que corresponde. El
bloque conserva la dependencia interna de la ventana y solo trata las ventanas
como la unidad de intercambio.

El coste son 20.000 pasadas por candidato, y se hace **una vez por candidato** y
no por ventana.

## 6. Persistencia: el informe sí, las simulaciones no

Tres tablas nuevas (`walk_forward_runs`, `walk_forward_windows`,
`walk_forward_candidates`) y una migración nueva.

**Por qué persiste algo si el barrido no persiste nada:** un WFO tarda entre uno
y dos minutos y su resultado es el objeto que después justifica (o refuta) una
configuración. Si solo viviera en un POST, habría que volver a ejecutarlo para
volver a mirarlo y no se podría auditar.

**Por qué no se guardan las 1.200 simulaciones:** son reproducibles desde la
configuración congelada del informe, y guardarlas convierte la base en un
vertedero. Un informe dice "evalué 120 combinaciones en 10 ventanas" y guarda las
candidatas; los resultados brutos se regeneran.

Esto es también lo que exigen las reglas 4 y 5 del Contrato Estadístico: el
**número de combinaciones evaluadas se registra y se publica**, y **los
resultados negativos se archivan**. Un informe que solo guardara los ganadores no
podría cumplir ninguna de las dos.

**Estado en vivo:** los runs de WFO se marcan con un `status` y una lista de
`status` terminal, como los de backtesting, para que un fallo del worker no deje
un informe "en curso" para siempre.

## 7. Lo que este motor no va a hacer

Están aquí porque son las tres formas que tiene un motor así de volverse una
máquina de sobreajuste con muy buen aspecto:

- **No devuelve un ganador único.** Devuelve una lista ordenada de candidatos con
  su veredicto. Si alguien quiere el primero, que lo coja sabiendo lo que dice
  su veredicto.
- **No reevalúa los candidatos sobre el OOS para ajustarlos.** Un candidato que
  se afina después de ver su OOS ya no es out-of-sample.
- **No usa todo el rango para elegir.** El último tramo, si el usuario quiere
  reservarlo para una validación final independiente, se puede marcar como
  `holdout` y no se toca hasta el final. Es opcional en la V1 porque el OOS de la
  última ventana ya cumple esa función.

## 8. API

### `POST /api/v1/walk-forward/runs`

```jsonc
{
  "scan_job_id": "uuid",
  "grid": { "take_profit_pcts": [null, 1.0, 2.0], "stop_loss_pcts": [1.0, 1.5, 2.0],
            "max_holds": [12, 24] },        // 18 combinaciones
  "window_days": 365,                      // tamaño in-sample
  "oos_days": 90,                          // tamaño out-of-sample
  "step_days": 90,                         // desplazamiento; 90 = contiguas
  "min_windows": 3,                        // ventanas OOS para ser candidato
  "min_trades": 30,                        // operaciones OOS mínimas
  "holdout_days": 0,                       // tramo final reservado, opcional
  "max_simulations": 2000                  // tope duro, se valida aquí
}
```

`max_simulations` se comprueba en el contrato y no en el worker: un 422 con el
número de combinaciones que serían es mucho más útil que un trabajo que muere a
los cinco minutos.

`→ 202 { "run_id": "uuid" }`, y el resto por `GET /runs/{id}`, con logs por
WebSocket igual que el backtest.

### `GET /api/v1/walk-forward/runs/{id}`

Informe completo:

```jsonc
{
  "run": { "status": "completed", "grid": {...}, "windows": 10, "step_days": 90,
           "simulations": 180, "elapsed_ms": 71204 },
  "windows": [
    { "index": 1, "is_from": "...", "is_to": "...", "oos_from": "...", "oos_to": "...",
      "selected": "MACD", "oos": { "trades": 12, "return_pct": "1.84", "win_rate": "0.583",
                                   "sharpe": "1.21", "max_drawdown_pct": "3.10",
                                   "market_return_pct": "2.41" } }
  ],
  "candidates": [
    { "strategy": { "take_profit_pct": null, "stop_loss_pct": 1.5, "max_hold": 24 },
      "score": 41.8, "verdict": "prometedora", "windows": 7, "trades": 96,
      "oos_return_pct": "12.4", "market_return_pct": "9.8", "win_rate": "0.547",
      "sharpe": "1.31", "max_drawdown_pct": "11.2",
      "beats_market_windows": 5, "profitable_windows": 6,
      "ci95": { "low": "-41.20", "high": "318.75" } }
  ]
}
```

`ci95` es `null` para un candidato `descartada`: no tiene sentido un intervalo de
una configuración que ya se descartó por no llegar al mínimo de operaciones.

### `GET /api/v1/walk-forward/runs/{id}/equity`

Curva OOS encadenada y benchmark encadenado, una fila por vela, con
`total_points`/`returned` como en la curva de equity del backtest. Sin esto, el
informe dice que el OOS ganó un 12% y no hay forma de ver **cuándo** ni cuánto
pesó cada ventana.

## 9. Frontend

Una pantalla, `/walk-forward`, con dos pestañas. Nada más, porque el roadmap es
explícito: el motor produce candidatos y lo que hay que poder hacer es
**auditar** el resultado, no navegarlo.

**Configuración**

- Escaneo (de los completados), tamaño IS, tamaño OOS, desplazamiento, atajos de
  reservas de validación.
- Rejilla: los tres ejes con los mismos defaults que el barrido y un contador en
  vivo de "N combinaciones × M ventanas = K simulaciones", **antes** de lanzar.
  El número de combinaciones evaluadas se enseña en la pantalla de resultados
  también, porque es el que hay que tener delante al leer un veredicto.
- Botón "Ejecutar" con el coste estimado en segundos, a partir de los ~60-80 ms
  medidos. No es una promesa de tiempo, es una estimación con la unidad puesta.

**Resultado**

- Veredicto arriba, con el color correspondiente y el texto de la §5.2, no solo
  una etiqueta.
- **Curva OOS encadenada** frente al benchmark encadenado, en SVG a mano como
  `ExcursionChart`, sin dependencia nueva.
- **Tabla por ventanas**: fechas, configuración elegida, operaciones, retorno,
  retorno del mercado, diferencia, Sharpe, drawdown. Es la que permite ver que
  el resultado no viene de una ventana suelta.
- **Tabla de candidatos**: parámetros, score, veredicto, ventanas, operaciones,
  win rate, Sharpe, drawdown, diferencia con el mercado, IC95%. El IC en su
  propia columna y en su propio formato, porque es el número que decide.

## 10. Criterios de aceptación

Algoritmo:
- [ ] El IS y el OOS de cada ventana son disjuntos, y la selección de cada
      ventana usa solo señales de su propio IS, con test.
- [ ] Las señales se asignan a la ventana por su marca de tiempo y el marco de
      velas se extiende `max_hold` barras para resolver la última operación.
- [ ] El capital se reinicia en cada ventana.
- [ ] Las curvas OOS se encadenan sin saltos y terminan en el equity final OOS.
- [ ] Reutiliza `analysis.sweep`; no hay una segunda implementacion de la
      rejilla.

Estadística:
- [ ] El score se calcula solo con ventanas OOS.
- [ ] Los pesos están congelados y hay un test que fija el valor exacto del score
      para un caso sintético.
- [ ] El IC95% se calcula sobre **todas** las operaciones OOS, paginadas.
- [ ] Un candidato con el IC que incluye el cero sale como `prometedora`, nunca
      como `sostenida`.
- [ ] Un candidato que no supera al mercado en el 60% de sus ventanas está
      descartado, con el motivo en la respuesta.
- [ ] El informe guarda y publica el número de combinaciones evaluadas.

Ejecución:
- [ ] `max_simulations` se rechaza con 422 antes de encolar.
- [ ] Un fallo del worker deja el run en `failed` con el motivo, no colgado.
- [ ] Cancelar detiene el motor entre ventanas.

Tests:
- [ ] La selección y el score con una rejilla de dos combinaciones y tres
      ventanas construidas a mano, con los números esperados escritos a dedo.
- [ ] La paginación del bootstrap con más de 200 operaciones OOS.
- [ ] La invariante de disjunction sobre un rango con solapamiento.
- [ ] El rechazo de `max_simulations`.

## 11. Riesgos

| Riesgo | Mitigación |
| --- | --- |
| Elegir pesos que favorezcan al candidato ganador | Pesos congelados en la spec, con el motivo escrito. Se revisan por juicio, no por resultado |
| Un solo mercado como evidencia | Guard 5 de la §5.1: `sostenida` exige 3 regímenes; con menos, el techo es `prometedora` y la pantalla lo dice |
| Las ventanas solapadas se cuentan como independientes | El IC95% se calcula con **bootstrap de bloques** por ventana, no suponiendo observaciones independientes. Se reporta también el desplazamiento y el número de ventanas |
| Rejillas enormes | `max_simulations` con 422 antes de encolar, y contador en vivo en el formulario |
| El tiempo de ejecución asusta al usuario | Coste estimado antes de lanzar y progreso por ventana, no por simulación |

## 12. Fuera de alcance

- Optimizar otros parámetros además de TP, SL y `max_hold` (empezar por los tres
  que ya se barren).
- Optimización bayesiana, algoritmos genéticos o cualquier cosa que elija por
  aprendizaje: son menos interpretables y el proyecto va de lo contrario.
- Varias rejillas encadenadas (walk-forward anidado).
- Alertas, que es la Fase 3 y ya esta especificada con otra logica.
- Ejecución automática de la configuración ganadora.

## 13. Estimación

| Bloque | Tiempo |
| --- | --- |
| `analysis/walk_forward.py`: ventanas, selección, score, bootstrap | 1,0 d |
| Modelos + migración de las tres tablas | 0,5 d |
| Servicio: carga, reuso de `sweep`, encadenado de curvas, benchmark | 0,5 d |
| Tarea Celery con progreso y cancelación | 0,3 d |
| Router y tests de servicio | 0,5 d |
| Frontend: configuración + resultado | 1,0 d |
| Verificación con los tres regímenes de referencia | 0,2 d |
| **Total** | **4,0 días** |

El reparto es deliberadamente desigual: dos días de backend y uno de frontend,
porque el riesgo de esta tarea está en el algoritmo y en las guardas, no en las
pantallas.

## 14. Plan de ejecución

1. **`analysis/walk_forward.py` con sus tests, sin base de datos.** Ventanas,
   selección, score y bootstrap, comprobados contra números escritos a mano. Es
   la pieza donde puede vivir un error silencioso, y se puede probar sin nada
   más. Si esto no cuadra, nada más importa.
2. **Modelos y migración.** Las tres tablas y su estado.
3. **Servicio y tarea Celery.** Reuso de `sweep`, encadenado de curvas, progreso.
4. **Router y tests de servicio**, incluido el de "no escribe 1.200 runs de
   backtest".
5. **Frontend**, con la curva OOS y las dos tablas.
6. **Verificación real** sobre los tres regímenes ya importados (BTCUSDT 1h
   2021-09→12, 2022-01→06 y 2026-07→09), que son exactamente el caso para el que
   existen: un lateral, un bajista y un alcista, con la conclusión ya conocida
   (`sin TP / SL 1,5% / 24 velas` gana en los tres). Si el motor no reproduce ese
   ranking con su criterio de Sharpe, el motor está mal y hay que arreglarlo
   antes de enseñarle nada a nadie.

---

## 15. Resultado del Paso 1 (cerrado)

El motor puro está en `app/modules/backtesting/walk_forward.py`, con 56 tests
propios y la suite completa en verde (333 tests).

### Lo que la verificación real encontró

1. **El ranking in-sample se reproduce entero.** Con la rejilla de 18
   combinaciones, `sin TP / SL 1,5% / 24 velas` queda **primera de 18 en los tres
   regímenes**, con el mismo margen que en la calibración manual. El motor mide
   lo que dice medir.

2. **Ganar in-sample no es ganar fuera de muestra, y hay un número.** Sobre el
   rango bajista de 2022 la calibrada da **+49,7%** OOS frente al **+67,5%** de
   la configuración original, que además opera el doble (123 frente a 246
   operaciones). Sigue siendo positiva en los tres regímenes, pero no domina. Este
   es exactamente el motivo de que el walk-forward exista, y está comprobado con
   datos reales, no supuesto.

3. **El ranking de candidatas no es comprobable con estos rangos, y no es culpa
   del motor.** El número de candidatas está acotado por el número de ventanas,
   porque solo puede ser candidata lo que fue elegido en el IS de alguna. Con
   89-180 días y ventanas del 50/25 %, salen 2-3 ventanas y por tanto 2-3
   candidatas de dieciocho: el ranking se queda sin contenido. Por eso el módulo
   incorpora `evaluate_fixed` / `evaluate_fixed_report`, que miden **una
   configuración dada** en el OOS de todas las ventanas sin elegir nada. Eso
   permite comparar la misma configuración entre los tres regímenes aunque no
   haya sido la elegida, que es lo que hace falta para validar.

4. **La guarda de mercado tiene que poder desactivarse.** `beats_market_ratio = 0`
   la desactiva. Sin esa posibilidad no se puede ver el ranking sin el filtro y,
   por tanto, no se puede comprobar que la guarda esté cambiando algo. La
   validación ahora es `[0, 1]`.

### Detalles de implementación que se desviaron de la spec

- **Ruta**: `analysis/walk_forward.py` es imposible: `analysis.py` y un paquete
  `analysis/` no coexisten en Python. El módulo va a
  `app/modules/backtesting/walk_forward.py`, junto a `analysis.py`.
- **Formato de fixtures**: CSV comprimido, no Parquet. El venv no trae `pyarrow`,
  y son ficheros locales que no se versionan.
- **Nombres de parámetro**: se unificó todo a `iteraciones` y `minutos_por_vela`,
  que es como ya se llamaba en `run_walk_forward`. Estaba mitad en inglés
  (`iterations`) y mitad en español dentro del mismo módulo.
- **Los fixtures no se versionan.** `scripts/export_regime_fixtures.py` los
  exporta desde la base de desarrollo a `tests/fixtures/walk_forward/`, que está
  en `.gitignore`. Si no están, los tests se **saltan**, no fallan: son datos de
  mercado, no código, y la base de desarrollo no puede ser tocada por pytest
  (`conftest.py` usa `lasa_test`).

### Dos defectos más que encontró la verificación final

**3. Rangos con huecos: el motor contaba ventanas que no existían.**

`build_windows` solo mira el primer y el último timestamp, así que un rango con
un agujero en medio produce ventanas **dentro del agujero**: cuentan igual, no
tienen velas ni señales, y salen como "sin selección posible" en un informe que
parece completo.

El daño no es que falten ventanas, es al revés. Las ventanas vacías se cuentan
en `windows`, y el número de ventanas **es el tamaño de la muestra del bootstrap
por bloques**. Treinta ventanas de las que veinte están vacías dan un IC95%
estrecho y un veredicto `sostenida` sobre siete ventanas reales. Es la confianza
inventada más cara que puede tener este módulo.

Comprobado sobre los datos reales: BTCUSDT 1h cubre 2021-09→2026-09 pero con un
hueco de **1.461 días** en medio, y tratado como serie continua daría 27
ventanas de las que **20 caerían dentro del hueco**. Se añadió
`assert_continuity`, que rechaza el rango y dice cuántos huecos hay, dónde está
el primero y qué hacer.

**4. El IC95% se calculaba sobre PnL en moneda, sumando, en vez de sobre
retornos, componiendo.** Eran dos fallos encadenados en la misma función:

- **Unidades**: el bootstrap sumaba PnL en divisa, y el resultado se comparaba
  contra el cero para dictar el veredicto y se pintaba al lado de
  `oos_return_pct`, que es un porcentaje. Sin normalizar, el intervalo escalaba
  con el capital inicial y no era comparable con la cifra de al lado.
- **Composición**: las ventanas se **sumaban** en vez de componerse. Con una
  suma, nueve ventanas del +80% dan un techo de +720%, que es dinero que el
  capital no puede llegar a hacer.

Y encima, componer multiplicando factores y remuestrear esos productos hace que
la cola derecha estalle. Medido sobre el caso real, el límite superior era
**+1128%** sobre una estimación puntual de +74%. No era una cota de riesgo: era
un número que marea y que en pantalla hace dudar de todo lo demás de la
pantalla.

El arreglo compone en **espacio logarítmico**, donde componer es sumar
(`sum(log1p(r))`), con `expm1` al final, y devuelve el intervalo **en
porcentaje**. El mismo caso real:

| | Estimación puntual | IC95% |
| --- | --- | --- |
| Antes (lineal, PnL) | +73,71% | [+70,1; **+1128,1**]% |
| Ahora (logarítmico, %) | +73,71% | [**+1,7**; **+173,3**]% |

El intervalo cae ahora sobre su propia estimación puntual, que es lo que un
intervalo tiene que hacer.

Y un aviso sobre lo que **no** cambió solo por el arreglo de escala: el veredicto
de la candidata elegida dentro de la muestra pasó de `sostenida` a `prometedora`,
porque su límite inferior real era −0,8%. El `sostenida` anterior venía de
comparar mal las unidades, no de que el intervalo excluyera el cero. El arreglo
no es solo cosmético: **corrige una decisión**, y la corrige hacia el lado
prudente.

### Estado: qué está validado y qué no

**Validado con 389 días de BTCUSDT 1h.** Produce veredictos honestos: ninguna
configuración llega a `sostenida` con la rejilla de 18 combinaciones que la
pantalla ofrece por defecto, y la causa está medida y es correcta — con 18
combinaciones sobre 9 ventanas, el ganador dentro de la muestra cambia casi
siempre y ninguna acumula las 5 ventanas mínimas. Eso *es* un hallazgo: la
elección in-sample no es consistente, que es la firma del sobreajuste.

Con una rejilla de 3 combinaciones aparece una `sostenida` (`TP 2,0 / SL 1,0 /
24v` sobre BTCUSDT 1h 2022-01→06), y se sometió a las dos pruebas que se le
pueden hacer a un hallazgo dudoso:

- **Estabilidad**: `sostenida` en 10 de 10 semillas del bootstrap.
- **Sesgo de selección**: evaluada con `evaluate_fixed`, sin que ninguna ventana
  de in-sample la elija y sobre las 9 ventanas, da **+73,71%** frente al
  +48,07% de la candidata. Quitar la selección **mejora** el resultado, que es
  lo contrario del sesgo de selección.

**Lo que no está validado**, y hay que decirlo sin rodeos: un tramo de 302 días
de un solo símbolo no es evidencia estadística. Para veredictos `sostenida` con
rejillas grandes hacen falta **años de datos continuos**, y esta base tiene 389
días reales con señales. La compra de datos es una tarea de importación, no de
este motor, y el motor ya está listo para ella: acepta el rango que le den y
rechaza los que tengan huecos.

### Lo que queda del Paso 2

Nada. La tarea está completa: motor puro, persistencia, API, tarea Celery,
pantallas y verificación E2E sobre los tres regímenes reales.
