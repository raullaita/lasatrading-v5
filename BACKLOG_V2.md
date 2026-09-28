# BACKLOG v2

Ideas que han salido del trabajo del módulo de Backtesting (Tareas 4, 4.5) y
del ciclo de calibración MAE/MFE, y que **quedan aplazadas** a propósito.

No es una lista de pendientes: es el registro de lo que se decidió *no* hacer
todavía y por qué. Cada entrada dice de dónde salió, qué se sabe ya y qué falta
para poder hacerla bien. La razón de escribirlas es que varias de estas ideas
parecían buenas en el momento y se cayeron al mirar los datos, y ese
razonamiento no se quiere perder.

Estado del módulo de Backtesting: **cerrado**. La Tarea 5 (Galería de
Indicadores), la 4.5 (Galería de Patrones) y el análisis estadístico quedan
fuera del pipeline principal a la espera de lo que se indique en la Tarea 6
(Alertas).

---

## 1. Bootstrap e intervalos de confianza dentro del módulo

**De dónde sale.** Durante la calibración hubo que calcular a mano, con un
script aparte, el IC95% del PnL de cada run (remuestreo de las operaciones con
reemplazo). El resultado cambió la conclusión varias veces: un +37,70% con el
mercado en +69% y un +20,78% con el mercado en +43% son, sin intervalo,
exactamente el mismo tipo de numero.

**Qué haría.** `GET /backtests/{id}/stats` con el IC95% del PnL, la
probabilidad de que el PnL sea positivo y el número de operaciones evaluadas.
Se puede calcular en Python sobre las operaciones ya persistidas, sin schema
nuevo.

**Por qué no ahora.** El script de uno-off ya cumple y el módulo se cierra.
Pero en cuanto las alertas empiecen a recomendar operaciones, el usuario va a
querer ver el intervalo en pantalla, y no es un número que se pueda inventar en
el frontend.

**Trampa conocida.** `page_size` está topado a 200 en `/trades`, así que un
bootstrap tiene que **paginar**. La primera versión de este cálculo se quedó
con las 200 primeras operaciones de un run de 440 y dio un intervalo
artificialmente estrecho: parecía mucho más concluyente de lo que era.

---

## 2. Correlación y beta de la estrategia frente al mercado

**De dónde sale.** Al medir el benchmark apareció que la estrategia correlaciona
0,759 con el activo y tiene beta 0,59. Sin esa cifra, "supera al mercado" y
"gana dinero" se confunden: una estrategia con beta 1,2 que gana en un mercado
alcista no ha hecho nada.

**Qué haría.** `correlation` y `beta` en el `BacktestBenchmarkOut`, calculados
sobre la curva de equity del run y la serie de cierres del mismo rango, ambos
alineados por timestamp en UTC. Es el mismo trabajo que ya se hizo a mano para
los tres regímenes.

**Por qué no ahora.** El benchmark de retorno y drawdown ya está integrado y
resuelve el 80% del problema. Beta y correlación son el siguiente 15% y pueden
esperar a que exista un sistema donde la pregunta sea relevante.

---

## 3. Galería de Patrones (Tarea 4.5, `docs/TASK_4_5_PATTERN_GALLERY.md`)

**De dónde sale.** Ya está especificada en `docs/` desde antes. Se aplazó dos
veces: primero porque el motor no estaba, y después porque documentar patrones
que luego demuestran no ser operables es trabajo que se tira.

**Qué se sabe ya, que cambia el diseño.** El ciclo de calibración dio una
lectura que el enunciado de la tarea no contempla: **4 de los 4 patrones del
escaneo de referencia tienen comportamiento distinto según el régimen**, y el
resultado depende más del conjunto de TP/SL que del patrón. La galería tal y
como está especificada (un gráfico de ejemplo por patrón, con marcadores) sigue
siendo válida, pero el botón "Escanear este patrón" debería llevar a un
formulario de backtest con los niveles que el barrido haya Recommended, no con
los del motor por defecto.

**Por qué no ahora.** `pattern_catalog.py` ya tiene `description`,
`direction`, `required_features` y `param_spec`, así que el backend es
pequeño; el trabajo real es el frontend (grid, detalle, `setMarkers` sobre
velas reales). Es UI pura, sin riesgo para los datos, y se puede hacer en
cualquier momento. Pero documentar sin saber qué patrones son operativos es
documentar de más.

---

## 4. Galería de Indicadores (Tarea 3.5, `docs/TASK_3_5_INDICATOR_GALLERY.md`)

**De dónde sale.** Especificada junto a la 4.5 y nunca implementada.

**Por qué es la menos prioritaria de las dos.** El módulo de Features ya tiene
`FeatureChart.tsx` con velas e indicadores superpuestos y selector de
indicadores. Una galería de indicadores informa de lo que el usuario ya puede
ver en cualquier run de features, con un gráfico de ejemplo por indicador. La
de patrones aporta algo que Features **no** tiene: la información de *dónde y
cuándo* se disparó una señal. Si se hace una, es la 4.5.

---

## 5. Criterio de selección de parámetros entre regímenes

**De dónde sale.** El hallazgo central del ciclo: elegir parámetros con el
"mejor PnL del barrido" sobre un solo mercado da sobreajuste casi siempre.
En los tres regímenes probados, la combinación elegida en el primero
(sin TP / SL 2,0%) quedó **3ª de 50 en el alcista, 20ª en el bajista y 2ª en el
chop**, mientras que la elegida por "mejor en el peor de los dos primeros"
(sin TP / SL 1,5%) quedó **1ª de 50 en los tres**, incluido el tercero, que no
participó en su elección. Solo 8 de 50 combinaciones superan al mercado en los
tres regímenes.

**Qué haría.** Un endpoint de "selección robusta" que evalúe una rejilla sobre
**varios escaneos** y ordene por la métrica del peor caso, no por la media. En
la UI sería un botón aparte del barrido actual ("Validar entre regímenes"),
porque el barrido de un solo run es una herramienta de diagnóstico y esto sería
una de selección.

**Por qué no ahora.** Requiere que el usuario tenga varios escaneos del mismo
símbolo en regímenes distintos, y hoy el barrido vive dentro de un run
concreto. Es un rediseño de la sección de calibración, no una función nueva.

**Cuidado con el Criterion.** Elegir el mejor de N por el peor de M casos sigue
siendo una selección y consume degrees of freedom. Con 3 regímenes y 50
combinaciones, el 1º de 50 tiene detrás ~1,7 combinaciones quebate por pura
suerte. Antes de creerse cualquier resultado hay que añadir un **cuarto**
régimen que no haya participado en la elección. Esta es la prueba pendiente más
importante del backlog.

---

## 6. Coste real de la operación: spread y slippage

**De dónde sale.** `PROJECT_GUIDELINES.md` §9 ("Reglas de Oro") dice que nunca
se opera con dinero real sin backtesting que incluya **spread, comisiones y
slippage**. El motor solo cobra comisión: `fee_bps` por lado, y ya se vio que
4 bps por lado se comen la estrategia en rangos laterales. El spread y el
slippage no están modelados.

**Qué haría.** Un slippage proporcional al tamaño de la orden (o por ATR) y
spread variable por franja horaria. Es un campo más en `StrategyConfig` y otra
columna en `BacktestTrade`, más una métrica de coste total en la tarjeta.

**Por qué no ahora.** Y porque los tres regímenes que hay en la base son
alcistas, y sin un régimen en caída no se puede ni medir si el slippage cambia
el veredicto. Es el segundo punto de la lista después del cuarto régimen.

---

## 7. Alertas: quéNIVEL de la estrategia hay que alertar

**De dónde sale.** La Tarea 6 (Alertas) es el siguiente paso del pipeline y el
backtest ya produce lo que hace falta para alimentarla. Pero la pregunta de
diseño es: ¿alerta una *señal de patrón* o una *operación candidata según la
estrategia calibrada*?

**Lo que el ciclo de calibración deja dicho.** Una señal de patrón aislada no
vale nada: la estrategia no gana, o gana, en función del nivel de stop y del
régimen. Alertar de un patrón suelto produce avisos de señales que el
backtest ya demostró que pierden. Al alerting de una "operación candidata"
(patrón + SL 1,5% + hold 24) se le puede exigir que solo avise cuando el
escaneo de referencia de ese símbolo haya respaldado la configuración.

**Por qué está aquí y no en el plan de la Tarea 6.** Porque es la decisión de
diseño más importante de esa tarea y conviene tomarla con estos datos delante,
no después.

---

## Resumen de referencias

| # | Idea | Origen | Bloqueante |
|---|---|---|---|
| 1 | Bootstrap e IC en el módulo | Calibración MAE/MFE | Que el usuario pida intervalos en pantalla |
| 2 | Correlación y beta | Medición del benchmark | Nada |
| 3 | Galería de Patrones (4.5) | Tarea 4 | Solo el frontend |
| 4 | Galería de Indicadores (3.5) | Tarea 3 | Redundante con `FeatureChart` |
| 5 | Selección robusta entre regímenes | Cross-validación | Rediseño de la sección de calibración |
| 6 | Spread y slippage | `PROJECT_GUIDELINES.md` §9 | Falta un régimen en caída usable |
| 7 | Nivel de la alerta (señal vs operación) | Inicio de la Tarea 6 | Nada: es una decisión |
