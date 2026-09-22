# LaSaTrading v5 — Backend

API REST y procesamiento en segundo plano de LaSaTrading. Construido con FastAPI, SQLAlchemy, Celery y Redis.

## Stack

- FastAPI + Uvicorn
- SQLAlchemy + Alembic + psycopg2 (PostgreSQL)
- Celery + Redis (broker y backend de resultados)
- pydantic-settings (configuración por variables de entorno)
- structlog (logging)
- Calidad: Ruff, pytest, pytest-asyncio

## Estructura

```
backend/
├── app/
│   ├── main.py            # Aplicación FastAPI, CORS y app de Celery
│   ├── config.py          # Configuración (pydantic-settings, lee .env)
│   ├── core/              # Infraestructura compartida
│   ├── modules/           # Módulos del pipeline (importación, features, ...)
│   │   └── data_import/   # Módulo de importación (Tarea 2, placeholder)
│   └── utils/             # Utilidades generales
├── alembic/               # Migraciones de base de datos
├── tests/                 # Suite de pruebas (pytest)
├── alembic.ini            # Configuración de Alembic
├── requirements.txt
└── .env.example           # Plantilla de variables de entorno
```

## Instalación y ejecución

Normalmente se gestiona desde el `manage.py` de la raíz. En desarrollo manual:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env

# API
.venv/bin/uvicorn app.main:app --reload --port 8000

# Worker de Celery
.venv/bin/celery -A app.main.celery_app worker -l INFO
```

## Migraciones (Alembic)

En la Tarea 1 no existen migraciones ni tablas reales (se crean en la Tarea 2). Cuando existan modelos, el flujo es:

```bash
.venv/bin/alembic revision --autogenerate -m "descripcion"
.venv/bin/alembic upgrade head
```

`backend/alembic/env.py` carga la URL de conexión desde la configuración de la aplicación (`app.config.get_settings().DATABASE_URL`).

## Endpoint de salud

`GET /health` devuelve el estado operativo de la API.

## Calidad

```bash
.venv/bin/ruff check .
.venv/bin/ruff format .
.venv/bin/pytest
```