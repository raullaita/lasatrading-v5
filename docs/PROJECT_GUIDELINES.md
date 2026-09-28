# LaSaTrading v5 — Directrices Generales del Proyecto

## 1. Descripción y Propósito

**LaSaTrading v5** es una herramienta de **investigación cuantitativa
automática** sobre patrones de mercado. El nombre honra a Laia y Sara, y la "v5"
indica que es la quinta iteración de este proyecto personal.

**Objetivo principal:** un sistema que encuentre, **por sí mismo** y de forma
reproducible, las configuraciones de estrategia con evidencia estadística a su
favor, sobre los datos que el propio sistema importa, escanea y simula. La
persona que lo usa tiene que poder auditar por qué el sistema ha considerado
una configuración válida, y por qué ha descartado las demás.

Este objetivo cambió de forma relevante a mitad del proyecto, y el cambio está
documentado en `BACKLOG_V2.md`. La versión anterior de estas directrices pedía
una herramienta con la que la persona *"encuentra, valida y opera patrones"*: es
decir, un **instrumento**. La versión actual pide un **investigador**: una
máquina que hace la búsqueda y explica el resultado. La diferencia no es de
interfaz, es de responsabilidad: si el sistema dice que una estrategia es
válida, la carga de la prueba es del sistema, no de quien lo consulta.

Consecuencia práctica: **cualquier bucle de trabajo manual que se repita es un
bug de arquitectura, no una tarea pendiente.** El ciclo de calibración
MAE/MFE —probar regímenes, barrer una rejilla, comparar contra el mercado,
arrastrar intervalos de confianza, repetir en otro mercado— es exactamente el
algoritmo que la Fase 2 va a ejecutar de forma automática. Se hizo a mano una vez
para entender el problema; no se vuelve a hacer a mano.

## 2. Filosofía de Diseño

- **Transparencia total:** Cada paso del pipeline debe ser visible, debuggeable
  y validable por separado. Esto incluye, y sobre todo, **las decisiones que
  toma el sistema automáticamente**: el optimizador no puede ser una caja negra
  que devuelve un número.
- **Sin "cajas negras":** No habrá pantallas que "hagan magia". El usuario debe
  ver qué datos entran, qué proceso se aplica y qué resultado sale en cada fase.
  Y en fase automática, también: qué se evaluó, qué se descartó y por qué.
- **Iteración incremental:** Cada módulo es independiente y puede ejecutarse,
  probarse y validarse por separado.
- **Seguridad ante todo:** Validación exhaustiva antes de cualquier operación
  con dinero real.
- **El escepticismo es parte del diseño:** un resultado que no supera al
  benchmark de su propio mercado no se presenta como éxito, por bonito que sea
  el número absoluto. Esta regla no es una preferencia estética: sin ella, un
  sistema de búsqueda automática fabricaría estrategias rentables con una
  eficacia proporcional al tamaño de su espacio de búsqueda.

## 3. Arquitectura de Alto Nivel

El sistema sigue una arquitectura cliente-servidor desacoplada, con
procesamiento en segundo plano para tareas pesadas:
- **Frontend:** Aplicación web reactiva para la interacción del usuario,
  visualización de datos y control del pipeline.
- **Backend:** API REST para la gestión de estado y lógica de negocio,
  orquestando tareas asíncronas.
- **Cola de tareas:** Sistema para ejecutar procesos largos (importación,
  backtesting, optimización) sin bloquear la interfaz.
- **Base de datos:** Almacenamiento relacional optimizado para series
  temporales.
- **Fuentes de datos:** Inicialmente Binance (pública), con arquitectura
  preparada para añadir más fuentes en el futuro.

## 4. Stack Tecnológico

- **Frontend:** React, Vite, Tailwind CSS, TypeScript. Calidad: ESLint,
  Prettier, Vitest. Gráficos: `lightweight-charts` (ya usado, sin dependencias
  nuevas previstas).
- **Backend:** Python, FastAPI. Calidad: Ruff (linter/formatter), pytest,
  pytest-asyncio. Numérico: `numpy` y `pandas`, ya en el motor de backtesting.
- **Procesamiento en segundo plano:** Celery + Redis.
- **Base de datos:** PostgreSQL con extensión TimescaleDB (para series
  temporales).
- **Gestión local:** Docker Compose (para PostgreSQL y Redis).
- **Gestión del proyecto:** Script unificado en Python (`manage.py`).

## 5. Estructura Conceptual del Proyecto

```
lasatrading-v5/
├── BACKLOG_V2.md             # Ideas aplazadas, con su motivo (no es una lista de pendientes)
├── docs/                     # Especificaciones por tarea
├── backend/                  # Código Python (FastAPI, Celery, Modelos)
├── frontend/                 # Código TypeScript/React (Vite, Tailwind)
├── manage.py                 # Script único de gestión del ciclo de vida
├── docker-compose.yml        # Definición de servicios de infraestructura
├── .gitignore                # Reglas de exclusión para control de versiones
└── README.md                 # Documentación principal del proyecto
```

## 6. Hoja de Ruta

El pipeline de datos no ha cambiado: Importación → Features → Patrones →
Backtesting. Lo que cambia es **qué se automatiza y en qué orden se construye**.

### FASE 1 · Data Explorer mejorado — Tarea 3.5 — *siguiente*

**Qué es:** un visualizador general de velas. Se elige símbolo y timeframe y
se ven las velas, con cualquier indicador y cualquier patrón superpuestos, **sin
necesidad de crear antes un job de features o un escaneo**.

**Estado real del código, que condiciona el diseño:**
- `/data` existe y es una **tabla** de grupos símbolo/timeframe con conteos,
  ordenación, paginación y borrado masivo. Su "preview" es un modal con **50
  velas en texto**, no un gráfico.
- Hay **dos implementaciones de gráfico de velas ya escritas**:
  `components/Features/FeatureChart.tsx` y `components/Patterns/PatternChart.tsx`.
  Ambas usan `lightweight-charts`, ambas manejan tema claro/oscuro y ambas
  resuelven el error de render de forma independiente.

**Consecuencia:** la Tarea 3.5 no es construir un gráfico desde cero, es
**extraer esas dos implementaciones a un componente único** y darle un sitio
donde vivir. El trabajo real es de consolidation y deGeneralización, y eso baja
la estimación a la mitad de lo que suponía "no tenemos visualizador".

**Absorbe la antigua Galería de Indicadores.** `docs/TASK_3_5_INDICATOR_GALLERY.md`
deja de ser una tarea aparte: un explorador con cualquier indicador superpuesto
*es* la galería de indicadores, con la diferencia de que funciona sobre datos
vivos y no sobre un job precalculado. Mantener las dos sería mantener dos formas
de hacer lo mismo. Ese documento queda marcado como absorbido, no como
descartado.

**Por qué es la Fase 1 y no la 3:** la Fase 2 producirá candidatos **en lote**,
varios por hora. Sin un visualizador no hay forma de mirarlos, y un optimizador
que no se puede inspeccionar es exactamente la caja negra que la §2 prohíbe.

### FASE 2 · Optimizador Walk-Forward — Tarea 5.5

**Qué es:** el motor que automatiza el ciclo de calibración manual. Recorre
ventanas temporales, simula una rejilla de parámetros sobre la ventana
*in-sample*, aplica la mejor configuración a la ventana *out-of-sample* sin
volver a mirarla, y repite. El resultado de cada configuración es un **veredicto
con evidencia**, no una posición en un ranking.

**Por qué walk-forward y no "el mejor barrido":** está medido. La configuración
que ganaba en el régimen alcista (sin TP / SL 2,0%) quedó **3ª de 50 en el
alcista, 20ª de 50 en el bajista y 2ª de 50 en el lateral**, en tres mercados
del mismo activo. Elegir por el mejor resultado de un tramo no generaliza, y
el fallo no es de método sino de suposición: que el régimen es estable. El
walk-forward no lo arregla por arte de magia, pero es el marco correcto para
un problema que es esencialmente no estacionario, y hace explícito dónde se
puede y dónde no se puede mirar.

**Requisitos no negociables de esta fase** (ver §7): separación estricta
in/out de muestra, número de combinaciones evaluadas registrado y publicado, y
ninguna configuración declarada válida sin superar al mercado y con intervalo
de confianza.

### FASE 3 · Alertas en tiempo real — Tarea 6

**Qué es:** notificaciones de señales en datos recientes, con la regla de que
**cada alerta apunta al run de backtesting que la respalda**, visible en la
propia notificación.

**Por qué va después de la 2 y no antes:** el ciclo de calibración respondió una
pregunta que condiciona el diseño de las alertas. Alertar de una *señal de
patrón* suelta produce avisos de señales que el backtest ya demostró que
pierden, porque el resultado depende más del nivel de stop y del régimen que
del propio patrón. La alerta que se puede defender es la de una **operación
candidata** —patrón más la configuración que el optimizador haya validado— y
esa configuración todavía no existe.

### FASE 4 · Ejecución

Integración futura para operar en real, inicialmente manual o
semi-automática. Fuera del alcance hasta que la Fase 2 produzca
configuraciones con evidencia y la Fase 3 las opere en vivo, que es donde se
descubre si un resultado con intervalo de confianza sobrevive el paso del papel.

## 7. Contrato Estadístico

Las reglas de este apartado no son preferencias: cada una responde a un error
concreto que ya se cometió durante el desarrollo del módulo de backtesting, y
que está documentado con sus números.

1. **Separación estricta in-sample / out-of-sample.** Los parámetros se eligen
   en in-sample y se aplican a out-of-sample. Un parámetro que se ha mirado en
   out-of-sample queda contaminado **para siempre**: hay que registrar qué se
   ha mirado en cada ventana, y no reusar esa ventana para decidir.
2. **Ninguna "configuración ganadora" sin las tres condiciones:** un mínimo de
   operaciones evaluadas, superar al benchmark del mercado, y el intervalo de
   confianza del PnL reportado. Un +20% con el mercado en +43% y un IC95% que
   incluye el cero es un resultado mediocre, y presentarlo como Radeon
   breakdown sin esas tres condiciones es un error de la herramienta.
3. **El benchmark es obligatorio en toda comparación.** Sin la cifra de
   "qué habría dado no operar", ningún número de retorno es interpretable. Ya
   está implementado en el resumen del run y en el barrido; cualquier pantalla
   nueva que muestre un PnL tiene que mostrar también el suyo.
4. **El número de combinaciones evaluadas se registra y se publica.** Elegir el
   mejor de 50 por el criterio del "peor caso" sigue siendo una selección, y el
   primero de 50 tiene detrás cerca de 1,7 combinaciones que ganan por azar. Un
   resultado sin el tamaño de la búsqueda a la que se le eligió es un resultado
   sin contexto.
5. **Los resultados negativos se archivan y se explican igual.** Un −3% que se
   sabe que es "el stop salta antes que el precio llegue" vale más que un +38%
   sin explicación. El registro de los descartados es la mitad del valor del
   sistema.
6. **Walk-forward no es un nombre, es una propiedad.** Si el mismo tramo de
   datos aparece en la ventana in-sample de una iteración y en la
   out-of-sample de otra, hay fuga aunque el código no tenga ningún `train_test_split`.

## 8. Convenciones Generales

- **Nomenclatura:** `snake_case` para backend y base de datos;
  `camelCase`/`PascalCase` para frontend.
- **Base de datos:** Las tablas de series temporales usarán claves primarias
  compuestas (timestamp, symbol, timeframe). Trazabilidad obligatoria (cada dato
  debe indicar de qué job de importación proviene).
- **Git:** Commits descriptivos. Nada de credenciales o archivos `.env` en el
  repositorio.
- **Manejo de errores:** Los fallos en una parte del pipeline (ej. un símbolo
  fallido en una importación masiva) no deben detener el proceso completo, sino
  registrarse y continuar.
- **Numeración de tareas:** un número de tarea no se reutiliza. Cuando una tarea
  se absorbe en otra, el documento antiguo se marca como absorbido y se dice en
  cuál, en lugar de borrarse: el razonamiento que lo Justificó sigue siendo
  válido aunque la implementación haya cambiado de sitio.

## 9. Gestión del Proyecto (Script `manage.py`)

Todo el ciclo de vida del desarrollo local se gestionará desde un único script
en la raíz del proyecto. Los comandos obligatorios son:
- `python manage.py setup`: Instalación inicial (dependencias, creación de
  archivos de entorno, arranque de infraestructura).
- `python manage.py start`: Levanta todos los servicios (Docker, Backend,
  Celery, Frontend).
- `python manage.py stop`: Detiene todos los servicios de forma ordenada y
  limpia.
- `python manage.py restart`: Ejecuta stop y start secuencialmente.
- `python manage.py status`: Muestra un resumen visual del estado de todos los
  servicios y puertos utilizados.
- `python manage.py logs [servicio]`: Muestra la salida de logs en tiempo real
  del servicio especificado.

## 10. Reglas de Oro para el Trading

- Nunca operar con dinero real sin un backtesting que incluya **spread,
  comisiones y slippage**. El motor hoy solo cobra comisión
  (`fee_bps` por lado); el spread y el slippage siguen sin modelar y están
  anotados en `BACKLOG_V2.md`.
- **La comisión no es un detalle contable.** Con 4 bps por lado, una estrategia
  de reversión media no gana dinero en un rango lateral. Cualquier resultado
  cercano a cero debe leerse primero como "coste de fricción", no como
  "estrategia neutra".
- Los datos son el activo más valioso: se priorizará la calidad, la detección de
  gaps y la no-duplicación sobre la velocidad de importación.
- El modo de importación por defecto será siempre "Merge" (actualizar
  existentes, añadir nuevos) para mantener la integridad del histórico.
- **Ningún dato de un mercado en tendencia se interpreta sin el de un mercado
  en contra.** La base local tiene, hoy, tres regímenes de BTCUSDT verificados
  (alcista, bajista, lateral) precisamente porque un resultado positive en un
  trending puede ser simplemente beta.

## 11. Estrategia Git

- **Estructura de ramas:** Una sola rama principal (`main`). No se usan ramas
  `develop` ni ramas `feature/`.
- **Commits:** Se agrupan por tarea completada, fix aplicado o feature añadida.
  Mensajes descriptivos y claros.
- **Push:** Se suben los cambios al repositorio remoto al completar cada tarea
  o fix importante.
- No se requiere flujo de pull requests ni protección de ramas (proyecto
  personal).

## 12. Estado Actual

| Fase | Tarea | Estado |
| --- | --- | --- |
| — | 1 · Inicialización | Completa |
| — | 2 · Importación de datos | Completa |
| — | 3 · Features | Completa |
| — | 4 · Detección de patrones | Completa |
| — | 4bis · Backtesting (motor, API, UI, análisis MAE/MFE, barrido, benchmark) | Completa. Ciclo de investigación cerrado. |
| 1 | 3.5 · Data Explorer mejorado | Pendiente (absorbe la antigua galería de indicadores) |
| 2 | 5.5 · Optimizador walk-forward | Pendiente |
| 3 | 6 · Alertas | Pendiente. Bloqueada por la 5.5. |
| 4 | 7 · Ejecución | Fuera de alcance |

**Regímenes de referencia disponibles** para validar cualquier trabajo
posterior, todos de BTCUSDT 1h y con los mismos 4 patrones de escaneo:

| Régimen | Rango | Mercado | Ocurrencias |
| --- | --- | --- | --- |
| Alcista | 2026-07-01 → 2026-09-27 | +43,81% | 94 |
| Lateral (chop) | 2021-09-01 → 2021-12-31 | −1,88% | 792 |
| Bajista | 2022-01-01 → 2022-06-30 | −56,85% | 1.169 |

## 13. Índice de Documentos

- `PROJECT_GUIDELINES.md`: Directrices generales del proyecto (este documento).
- `BACKLOG_V2.md` (raíz): Ideas aplazadas con su motivo. **Antes de proponer
  trabajo nuevo, leer esto.**
- `TASK_1_INITIALIZATION.md`: Tarea 1 — Inicialización del proyecto.
- `TASK_2_IMPORT_IMPLEMENTATION.md`: Tarea 2 — Implementación de la importación.
- `TASK_3_FEATURES_IMPLEMENTATION.md`: Tarea 3 — Cálculo de features.
- `TASK_3_5_DATA_EXPLORER.md`: Tarea 3.5 — Data Explorer mejorado (Fase 1).
- `TASK_3_5_INDICATOR_GALLERY.md`: **Absorbida** en la Tarea 3.5.
- `TASK_4_PATTERN_DETECTION.md`: Tarea 4 — Detección de patrones.
- `TASK_4_5_PATTERN_GALLERY.md`: Tarea 4.5 — Galería de patrones. Aplazada
  hasta que la 5.5 diga qué patrones son operativos.
- `TASK_5_5_WALK_FORWARD.md`: Tarea 5.5 — Optimizador walk-forward (Fase 2).
- `TASK_6_ALERTS.md`: Tarea 6 — Alertas en tiempo real (Fase 3).
