# Tarea 3.5: Data Explorer Unificado

> Sustituye a `TASK_3_5_INDICATOR_GALLERY.md`, que queda **absorbida** por
> esta (ver el aviso al principio de aquel documento y la regla de la sección 8
> de `PROJECT_GUIDELINES.md`).

## 1. Objetivo

Un único componente de visualización de velas, reutilizable y sin job previo:
se elige símbolo y timeframe, se ve el gráfico, y encima se superponen los
indicadores que ya existen en la base y las detecciones de un escaneo
seleccionado. Todo lo que se pinte tiene que ser trazable hasta el job que lo
produjo.

Es la Fase 1 del roadmap y va **antes** que el optimizador porque la Fase 2
producirá candidatos en lote: sin una forma de mirar un gráfico, el
optimizador es exactamente la caja negra que la sección 2 de las directrices
prohíbe.

## 2. Punto de partida verificado

No se empieza de cero. Esto es lo que hay hoy, comprobado en el código:

**Ya existe, y hay que reutilizar:**

| Pieza | Dónde | Qué aporta |
| --- | --- | --- |
| `FeatureChart.tsx` | `components/Features/` | Gráfico de velas + indicadores, con merge de filas por timestamp (`prepareRows`) |
| `PatternChart.tsx` | `components/Patterns/` | Lo anterior **más** `setMarkers` y `highlightTimestamp` con ventana de 60 velas |
| `patternUtils.ts` | `components/Patterns/` | `isFiniteNumber`, `toUnixSeconds`, `prepareMarkers`, ya con 12 tests en `patternUtils.test.ts` |
| `GET /patterns/scans/{id}/chart` | `patterns/router.py` | Velas + indicadores pivotados + occurrences, con overrides de símbolo, timeframe, rango y features |
| `_load_features_pivot` | `patterns/service.py` | Pivote en memoria de `features` (largo → ancho) con una sola consulta |
| Tabla `features` | `features/models.py` | Valores de indicadores **con `feature_job_id` nullable**: existen sin job |

**Duplicación a eliminar** (medida, no supuesta):

1. `THEME_COLORS` — objeto idéntico, 20 líneas duplicadas.
2. `INDICATOR_COLORS` — la misma paleta de 7 colores en ambos ficheros. El
   comentario de `PatternChart` dice que se mantiene aparte "a propósito" para
   que un RSI se reconozca igual en las dos pantallas, y el resultado es que el
   mismo array está copiado. Se unifica.
3. `toUnixSeconds` e `isFiniteNumber` — definidos dentro de `FeatureChart` y
   además en `patternUtils`.
4. El bloque `useEffect` de creación del chart: unas 60 líneas idénticas
   (`createChart` con las mismas opciones, mismo `ResizeObserver`, mismo
   `try/catch` con `chart.remove()` y el mismo cleanup).
5. La tarjeta, el título y los tres estados (sin datos / filas no graficables /
   error de render).

**Formato de datos distinto, que hay que decidir:** `FeatureChart` recibe filas
ya fusionadas (`{timestamp, ohlc, indicators}`); `PatternChart` recibe velas e
indicadores **por separado** (`Record<string, point[]>`). El unificado adopta el
formato fusionado —es el que necesita la vista de rango variable— y el
consumidor de `/scans/{id}/chart` convierte con un adaptador de tres líneas.

**Defecto real que se corrige de paso:** en ambos ficheros, `symbol` y
`timeframe` están en las dependencias del `useEffect` aunque solo se usan como
texto de la cabecera. Cambiar el símbolo por lo mismo que ya está seleccionado
tear-down y reconstruye el gráfico entero. Peor: como `rows` se memoriza sobre
las props, cualquier array nuevo recrea el chart. El diseño nuevo separa
**vida del chart** de **vida de los datos** (ver 5.1).

## 3. Decisiones de diseño

### 3.1 · Los indicadores del gráfico son los de la base. Nunca se calculan al vuelo

La pregunta se plantea en el enunciado: superponer los indicadores que existen
en la BD "o calcularlos al vuelo si es viable". **La respuesta es que solo los
que existen en la BD, siempre.** Tres razones:

1. **Sería una tercera copia del cálculo.** `pattern_catalog.py` ya replica los
   f-strings de `FeatureService._calculate_indicator` para resolver
   `required_features`, precisamente para no duplicar el criterio de nombrado. Un
   cálculo en el endpoint del chart sería la tercera implementación del mismo
   criterio de nombres, y las copias divergen: es el mecanismo exacto del bug de
   RSI documentado en `candles.py`.
2. **El warm-up haría que el gráfico mintiera en los bordes.** Una SMA de 20
   necesita 20 velas previas; si el chart pide solo el rango visible, los
   primeros 20 puntos de cada indicador serían `NaN` o, peor, un valor
   calculado con menos historia que el que está almacenado. Habría dos
   números para el mismo timestamp según de dónde saliera, y el usuario no
   podría saber cuál está viendo.
3. **Rompe la trazabilidad.** Si un valor aparece en pantalla sin job que lo
   haya producido, la cadena "dato → job → escaneo → backtest → alerta" se
   rompe en el primer eslabón.

En su lugar, el explorador **dice la verdad sobre lo que falta** y ofrece
arreglarlo: si pides `EMA_50` y no hay datos en el rango, sale "sin datos en
este rango" con un botón **"Calcular EMA_50 para este rango"** que lanza el job
de features existente. Ese botón es el criterio de aceptación "Usar este
indicador" de la antigua galería, reencuadrado en algo que de verdad hace falta.

### 3.2 · Muestreo por paso constante, con los dos extremos, y los indicadores en las timestamps elegidas

Un año de 1h son 8.760 velas, y × 8 indicadores son ~70.000 filas de `features`
en un JSON. Pero **las velas no se pueden muestrear sin más**: una vela saltada
deforma el gráfico y, si los indicadores se muestrean aparte, el overlay queda
desalineado en el tiempo.

Procedimiento, en este orden:
1. Se cuenta el total de velas del rango.
2. Si supera `max_points`, se elige un paso constante y se conservan las velas
   cuyo índice cumple `i % paso == 0`, **más la última siempre**.
3. Los indicadores se piden **solo para esas timestamps**.

Es el mismo criterio que ya se usó y depuró en `get_run_equity`, donde perder la
última vela fue un bug real (`analysis.py`, docstring del módulo). La respuesta
lleva `total_points`, `returned` y el rango efectivo, y la UI lo dice en voz
alta: "mostrando 1.500 de 8.760 velas". Un gráfico que finge estar completo es
peor que uno que enseña menos y lo dice.

### 3.3 · Los indicadores ausentes se declaran, no se callan

Hoy `_load_features_pivot` hace `wide.columns & set(names)`: los indicadores
pedidos que no existen **desaparecen sin avisar**. Con la cobertura real de la
base eso es un problema, no un detalle:

```
BTCUSDT 1h  EMA_20          2021-09-01 → 2026-09-27
BTCUSDT 1h  EMA_50                     → 2026-07-01 → 2026-09-27
BTCUSDT 1h  ATR_14, BBL/BBM/BBU_20_2.0 → 2025-09-24 → 2026-09-24
```

Es decir, hay indicadores que **empiezan 5 años después** que otros. Al
seleccionar un rango de 2022 y pedir `ATR_14`, el gráfico lo omitiría en
silencio y el usuario concluiría que ATR no está implementado.

La respuesta gana un campo `missing_indicators: string[]` y la UI lo pinta como
enlace al cálculo, uno por uno.

### 3.4 · La ruta

**Propuesta: `/data` con el gráfico como panel, y el estado en la query
string.** `?symbol=BTCUSDT&timeframe=1h&from=...&to=...&features=EMA_20,RSI_14&scan=<id>`

Motivos:
- El inventario de `/data` **ya es la navegación**: pinchar una fila es
  selections símbolo y timeframe. Una pantalla de gráfico aparte obligaría a
  reimplementar el selector sobre datos que ya están cargados.
- Es compartible por URL, que es la forma de que "mira este gráfico y este
  escaneo" sea una frase y no una sesión de ocho clics.
- No añade un item al menú lateral ni duplica el estado.

`/data-explorer` como ruta aparte queda como alternativa si se prefiere separar
las dos/screens, pero el criterio es que el gráfico vive **dentro** de `/data`.

### 3.5 · Backend: un servicio, dos rutas

`PatternScanService.get_chart_data()` ya recibe símbolo, timeframe, rango y
features **independientemente del job**. Lo único que impide al explorador
usarlo es que la ruta expone `job_id` como obligatorio.

```
GET /api/v1/patterns/chart
    ?symbol=BTCUSDT&timeframe=1h&date_from=...&date_to=...
    [&features=EMA_20,RSI_14][&patterns=MACD_CROSS_BULLISH][&scan=<id>]
    [&max_points=1500]
```

La ruta de escaneo pasa a **delegar** en la nueva, con los valores por defecto
del job. Un servicio, dos entradas: el mismo criterio que ya se aplicó con
`load_candles`, extraído porque tres módulos tenían copias divergentes.

Añadido también:
```
GET /api/v1/features/available?symbol=&timeframe=
→ { indicators: [{name, params, from, to, points}], }
```
para que el selector **solo ofrezca lo que existe**, con su cobertura real, y
pueda ofrecer "calcular" para el resto.

## 4. API

### `GET /api/v1/patterns/chart`

```jsonc
{
  "symbol": "BTCUSDT",
  "timeframe": "1h",
  "date_from": "2022-01-01T00:00:00Z",
  "date_to": "2022-06-30T23:59:59Z",
  "candles": [ { "timestamp": "...", "open": 0, "high": 0, "low": 0, "close": 0, "volume": 0 } ],
  "indicators": { "EMA_20": [ { "timestamp": "...", "value": 0 } ] },
  "missing_indicators": ["ATR_14"],
  "markers": [ { "timestamp": "...", "pattern_name": "MACD_CROSS_BULLISH", "direction": "bullish" } ],
  "total_points": 4344,
  "returned": 1500,
  "step": 3,
  "sampled": true
}
```

Reglas:
- `max_points` por defecto **1.500**, máximo **5.000**. Es un tope de payload, no
  de datos: con paso entero el muestreo no sesga la escala temporal.
- `step = max(1, ceil(total_points / max_points))`.
- `markers` solo si se pasa `scan`. Sin escaneo, la lista es `[]` y la UI oculta
  el panel de detecciones: no se puede marcar lo que no se ha escaneado.
- `missing_indicators` solo cuando se piden explícitamente y no hay filas.

### `GET /api/v1/features/available`

```jsonc
{
  "symbol": "BTCUSDT",
  "timeframe": "1h",
  "indicators": [
    { "name": "EMA_20", "params": { "length": 20 }, "from": "2021-09-01T00:00:00Z",
      "to": "2026-09-27T23:00:00Z", "points": 16105 }
  ]
}
```

## 5. Frontend

### 5.1 · `components/charts/UnifiedChart.tsx`

```ts
export interface ChartRow {
  timestamp: string;
  ohlc: { open: number; high: number; low: number; close: number } | null;
  indicators: Record<string, number>;
}

interface UnifiedChartProps {
  rows: ChartRow[];
  markers?: PatternChartMarker[];
  /** Lleva la vista a esta vela con una ventana alrededor. */
  highlightTimestamp?: string | null;
  title?: string;
  subtitle?: string;
  height?: number;
  onMarkerClick?: (marker: PatternChartMarker) => void;
}
```

Reglas de ciclo de vida, que es la parte que los dos componentes actuales hacen
peor:

1. El chart se crea en un `useEffect` **solo al montar y al cambiar el tema**.
   Nunca por un cambio de datos.
2. Las series se guardan en `useRef` y los `setData` van en efectos separados.
   Cambiar un indicador es un `setData` sobre una serie existente, no un
   teardown.
3. `symbol`/`timeframe`/`title` **no** son dependencias del efecto de creación:
   son texto de la cabecera.
4. `markers` se aplican sobre la referencia de la serie de velas
   (`setMarkers` va en la serie, no en el chart).
5. Al desmontar: `chart.remove()` y desconectar el `ResizeObserver`. Nunca se
   reusa una instancia de lightweight-charts.

### 5.2 · `components/charts/chartData.ts` — la lógica pura, testeable

`prepareRows`, `toUnixSeconds`, `isFiniteNumber`, `SERIES_COLORS`,
`THEME_COLORS`, `toChartRows` (adaptador de `/scans/{id}/chart` a `ChartRow[]`) y
`pickOverlaySteps` (qué velas se pintan dado un total y un tope).

Vive aparte del componente **por el motivo que ya funciona en el proyecto**:
`patternUtils.ts` + `patternUtils.test.ts` con 12 tests sin DOM. Es la única
forma de probar el merge por timestamp, el filtrado de no-finitos y el
muestreo con la última vela incluida, que son las tres cosas que fallan sin dar
ningún error visible.

### 5.3 · Página

`/data` gana un panel de gráfico a la derecha del inventario:

- **Selector de rango**: presets (7d, 30d, 90d, 6m, 1a, todo lo disponible) y
  dos `datetime` para rangos a medida. El preset "todo" se calcula desde el
  `date_from`/`date_to` que ya devuelve `/data/summary`.
- **Selector de indicadores**: checkboxes con el nombre tal cual lo calcula el
  motor (`EMA_20`, `MACD_12_26_9`), no con los parámetros desglosados. El
  nombre **es** la identidad de la serie y así lo resuelve `required_features`.
  Los ausentes en el rango salen en otro grupo, con su enlace a "calcular".
- **Selector de escaneo**: opcional. Al elegirlo aparecen los markers filtrados
  por patrón.
- **Aviso de muestreo**: si `sampled`, texto explícito con `returned` de
  `total_points`.
- **`missing_indicators`**: lista con "calcular este indicador para este rango".

### 5.4 · Migración de los dos consumidores

- `FeatureDetail.tsx` (línea 331) → `UnifiedChart` con `rows={toChartRows(...)}`.
  `FeatureChart.tsx` **se borra**.
- `ScanDetail.tsx` (línea 544) → `UnifiedChart` conservando `highlightTimestamp`.
  `PatternChart.tsx` **se borra**.

`EquityChart.tsx` **no se toca**: es un gráfico de líneas, sin velas ni markers,
y meterlo en el unificado sería forzar el caso común para encajar un caso
distinto. Se queda con su `createChart` propio, y su comentario de que
lightweight-charts no admite reutilizar instancias pasa a ser la razón de que
sean dos componentes y no uno.

## 6. Criterios de aceptación

Funcionales:
- [ ] Con un símbolo y timeframe con velas, el gráfico se pinta sin crear
      ningún job.
- [ ] Los indicadores disponibles en el rango salen superpuestos, sin solaparse
      y con el color estable de una serie a otra (el mismo nombre, mismo color,
      en cualquier pantalla).
- [ ] Un indicador pedido y ausente sale en `missing_indicators` con su botón
      de cálculo, no desaparece.
- [ ] Al elegir un escaneo aparecen los markers en las velas correctas.
- [ ] El tema claro/oscuro se aplica a la vez, sin recrear el chart.
- [ ] Marcar o desmarcar un indicador **no** reconstruye el chart.
- [ ] Con un rango de 8.760 velas sale el aviso de muestreo y los indicadores
      quedan alineados con las velas mostradas.
- [ ] La vista es compartible por URL y al abrirla se restaura.
- [ ] `FeatureDetail` y `ScanDetail` siguen funcionando, con el mismo aspecto.
- [ ] El "Ver en gráfico" de la tabla de ocurrencias sigue centrando la vela.

Técnicos:
- [ ] `prepareRows`, `pickOverlaySteps` y `toChartRows` con tests, sin DOM.
- [ ] Ningún cálculo de indicadores fuera de `FeatureService`.
- [ ] Un chart por instancia; cero recreaciones por cambio de datos.
- [ ] ESLint, `tsc -b`, `npm run build` y vitest en verde.
- [ ] Sin dependencias nuevas: `lightweight-charts` ya está instalada.

## 7. Riesgos

| Riesgo | Mitigación |
| --- | --- |
| Romper `ScanDetail` al cambiar el formato de datos | Adaptador `toChartRows` + los 12 tests de `patternUtils` siguen vivos contra el formato antiguo |
| Payload enorme con rango de años | `max_points` con tope duro, paso constante y respuesta con `returned`/`total_points` |
| Recreación del chart en cada toggle | Vida del chart separada de la de los datos, con test que cuente `createChart` |
| Que el muestreo desalinee el overlay | Los indicadores se piden en las timestamps de las velas **elegidas**, no aparte |
| Que el explorador se convierta en otra forma de calcular features | Sin endpoint de cálculo; solo se enlaza al job existente |

## 8. Fuera de alcance

- Cualquier indicador que no produzca `FeatureService`. Si hace falta RSI 21 o
  un VWAP, es una tarea de Features, no del explorador.
- Polígonos, herramientas de dibujo y guardado de vistas.
- Exportar a imagen o CSV.
- Detección **en vivo** dentro del explorador: escanear es un job, y el
  explorador lee jobs. Mezclarlos aquí rompería la separación entre lectura y
  escritura que sostiene el resto del pipeline.

## 9. Estimación

| Bloque | Tiempo |
| --- | --- |
| `chartData.ts` + tests | 0,5 d |
| `UnifiedChart.tsx` | 0,5 d |
| Backend: ruta sin job, `max_points`, `missing_indicators`, `/features/available` | 0,5 d |
| Panel del explorador y selectores | 0,5 d |
| Migración de los dos consumidores y borrado de los duplicados | 0,5 d |
| **Total** | **2,5 días** |

La migración no se considera opcional ni decorativa: sin ella quedan dos
implementaciones de gráfico y la siguiente sesión vuelve a divergir.
