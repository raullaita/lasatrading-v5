# LaSaTrading v5 — Directrices Generales del Proyecto

## 1. Descripción y Propósito
**LaSaTrading v5** es una plataforma de trading algorítmico diseñada para descubrir, validar y operar patrones de mercado. El nombre honra a Laia y Sara, y la "v5" indica que es la quinta iteración de este proyecto personal.

**Objetivo principal:** Construir una aplicación web que permita importar datos históricos, calcular indicadores, detectar patrones, validarlos mediante backtesting riguroso y, finalmente, operar en real (con QuantFury) solo cuando se encuentren patrones estadísticamente rentables.

## 2. Filosofía de Diseño
- **Transparencia total:** Cada paso del pipeline debe ser visible, debuggeable y validable por separado.
- **Sin "cajas negras":** No habrá pantallas que "hagan magia". El usuario debe ver qué datos entran, qué proceso se aplica y qué resultado sale en cada fase.
- **Iteración incremental:** Cada módulo es independiente y puede ejecutarse, probarse y validarse por separado.
- **Seguridad ante todo:** Validación exhaustiva antes de cualquier operación con dinero real.

## 3. Arquitectura de Alto Nivel
El sistema sigue una arquitectura cliente-servidor desacoplada, con procesamiento en segundo plano para tareas pesadas:
- **Frontend:** Aplicación web reactiva para la interacción del usuario, visualización de datos y control del pipeline.
- **Backend:** API REST para la gestión de estado y lógica de negocio, orquestando tareas asíncronas.
- **Cola de tareas:** Sistema para ejecutar procesos largos (importación, backtesting) sin bloquear la interfaz.
- **Base de datos:** Almacenamiento relacional optimizado para series temporales.
- **Fuentes de datos:** Inicialmente Binance (pública), con arquitectura preparada para añadir más fuentes en el futuro.

## 4. Stack Tecnológico
- **Frontend:** React, Vite, Tailwind CSS, TypeScript. Calidad: ESLint, Prettier, Vitest.
- **Backend:** Python, FastAPI. Calidad: Ruff (linter/formatter), pytest, pytest-asyncio.
- **Procesamiento en segundo plano:** Celery + Redis.
- **Base de datos:** PostgreSQL con extensión TimescaleDB (para series temporales).
- **Gestión local:** Docker Compose (para PostgreSQL y Redis).
- **Gestión del proyecto:** Script unificado en Python (`manage.py`).

## 5. Estructura Conceptual del Proyecto
lasatrading-v5/
├── docs/                   # Documentación del proyecto
├── backend/                # Código Python (FastAPI, Celery, Modelos)
├── frontend/               # Código TypeScript/React (Vite, Tailwind)
├── manage.py               # Script único de gestión del ciclo de vida
├── docker-compose.yml      # Definición de servicios de infraestructura
├── .gitignore              # Reglas de exclusión para control de versiones
└── README.md               # Documentación principal del proyecto

## 6. Módulos del Pipeline
El flujo de trabajo se divide en fases secuenciales e independientes:
1. **Importación de Datos:** Descarga, normalización y almacenamiento de datos OHLCV (fuente inicial: Binance).
2. **Cálculo de Features:** Generación de indicadores técnicos y transformaciones sobre los datos crudos.
3. **Detección de Patrones:** Escaneo de los datos procesados en busca de condiciones predefinidas.
4. **Backtesting:** Simulación histórica de los patrones detectados con gestión de riesgo y costes.
5. **Alertas:** Notificaciones en tiempo real cuando se detectan patrones válidos en datos recientes.
6. **Ejecución:** Integración futura para la operación (inicialmente manual/semi-automática vía QuantFury).

## 7. Convenciones Generales
- **Nomenclatura:** `snake_case` para backend y base de datos; `camelCase`/`PascalCase` para frontend.
- **Base de datos:** Las tablas de series temporales usarán claves primarias compuestas (timestamp, symbol, timeframe). Trazabilidad obligatoria (cada dato debe indicar de qué job de importación proviene).
- **Git:** Commits descriptivos. Ramas `feature/` para nuevas funcionalidades. Nada de credenciales o archivos `.env` en el repositorio.
- **Manejo de errores:** Los fallos en una parte del pipeline (ej. un símbolo fallido en una importación masiva) no deben detener el proceso completo, sino registrarse y continuar.

## 8. Gestión del Proyecto (Script `manage.py`)
Todo el ciclo de vida del desarrollo local se gestionará desde un único script en la raíz del proyecto. Los comandos obligatorios son:
- `python manage.py setup`: Instalación inicial (dependencias, creación de archivos de entorno, arranque de infraestructura).
- `python manage.py start`: Levanta todos los servicios (Docker, Backend, Celery, Frontend).
- `python manage.py stop`: Detiene todos los servicios de forma ordenada y limpia.
- `python manage.py restart`: Ejecuta stop y start secuencialmente.
- `python manage.py status`: Muestra un resumen visual del estado de cada servicio y puertos utilizados.
- `python manage.py logs [servicio]`: Muestra la salida de logs en tiempo real del servicio especificado.

## 9. Reglas de Oro para el Trading
- Nunca operar con dinero real sin un backtesting que incluya spread, comisiones y slippage.
- Los datos son el activo más valioso: se priorizará la calidad, la detección de gaps y la no-duplicación sobre la velocidad de importación.
- El modo de importación por defecto será siempre "Merge" (actualizar existentes, añadir nuevos) para mantener la integridad del histórico.

## 10. Estrategia Git
- **Estructura de ramas:** Una sola rama principal (`main`). No se usan ramas `develop` ni ramas `feature/`.
- **Commits:** Se agrupan por tarea completada, fix aplicado o feature añadida. Mensajes descriptivos y claros.
- **Push:** Se suben los cambios al repositorio remoto al completar cada tarea o fix importante.
- No se requiere flujo de pull requests ni protección de ramas (proyecto personal).

## 11. Índice de Documentos
- `PROJECT_GUIDELINES.md`: Directrices generales del proyecto.
- `TASK_1_INITIALIZATION.md`: Tarea 1 — Inicialización del proyecto.
- `TASK_2_IMPORT_IMPLEMENTATION.md`: Tarea 2 — Implementación de la importación de datos.