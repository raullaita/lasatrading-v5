# LaSaTrading v5

Plataforma de trading algorítmico para descubrir, validar y operar patrones de mercado. El proyecto es la quinta iteración de una plataforma personal que permite importar datos históricos, calcular indicadores, detectar patrones, validarlos mediante backtesting y, en el futuro, operar en real.

## Arquitectura

- **Frontend:** React 18 + TypeScript + Vite 5 + Tailwind CSS 3 (puerto 5173).
- **Backend:** FastAPI con Celery para tareas en segundo plano (puerto 8000).
- **Infraestructura:** PostgreSQL 15 y Redis 7 en contenedores Docker Compose.
- **Gestión:** Script unificado `manage.py` para todo el ciclo de vida local.

## Requisitos previos

- Python >= 3.9
- Node.js >= 18
- Docker con Docker Compose (versión 2 o `docker-compose` independiente)

## Instalación rápida

```bash
python manage.py setup
```

El comando `setup` verifica el entorno, crea `backend/.venv`, instala las dependencias de backend y frontend, copia `.env.example` a `.env`, inicializa el repositorio Git con el commit inicial y levanta la infraestructura Docker.

## Uso diario

| Comando | Descripción |
| --- | --- |
| `python manage.py start` | Levanta Docker, backend, worker de Celery y frontend en segundo plano. |
| `python manage.py status` | Muestra el estado de todos los servicios y las URLs de acceso. |
| `python manage.py logs [backend\|celery\|frontend\|docker]` | Muestra los logs en tiempo real de un servicio. |
| `python manage.py restart` | Detiene y vuelve a arrancar todos los servicios. |
| `python manage.py stop` | Detiene todos los servicios y la infraestructura de forma ordenada. |

### URLs

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- Documentación de la API (Swagger): http://localhost:8000/docs

## Documentación

- `docs/PROJECT_GUIDELINES.md`: Directrices generales del proyecto.
- `docs/TASK_1_INITIALIZATION.md`: Tarea 1 — Inicialización del proyecto.
- `docs/TASK_2_IMPORT_IMPLEMENTATION.md`: Tarea 2 — Implementación de la importación de datos.