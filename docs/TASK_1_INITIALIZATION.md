# Tarea 1: Inicialización del Proyecto

## 1. Objetivo
Crear la estructura base del proyecto LaSaTrading v5 con todas las dependencias, configuraciones y scripts de gestión necesarios para empezar a desarrollar. Al finalizar esta tarea, el proyecto debe poder arrancarse completamente con el comando de gestión y todos los servicios deben responder correctamente.

## 2. Criterios de Aceptación
- Estructura de carpetas creada según las directrices del documento general.
- Backend FastAPI arrancando y respondiendo en un endpoint de salud (/health).
- Frontend React arrancando y mostrando una pantalla de bienvenida básica.
- PostgreSQL y Redis corriendo correctamente en contenedores Docker.
- Script de gestión funcionando con todos los comandos especificados.
- Documentación básica (READMEs) creada en la raíz y en cada subproyecto.

## 3. Estructura de Carpetas Requerida
El proyecto debe seguir estrictamente la siguiente jerarquía conceptual:
- Raíz: docs/, backend/, frontend/, manage.py, docker-compose.yml, .gitignore, README.md
- Backend: app/ (con main.py, config.py, modules/, core/, utils/), alembic/, requirements.txt, .env.example, README.md
- Frontend: src/ (con pages/, components/, services/, types/, App.tsx, main.tsx, index.css), public/, package.json, vite.config.ts, tailwind.config.js, tsconfig.json, README.md

## 4. Especificaciones de Dependencias
- Backend: Debe incluir FastAPI, Uvicorn, SQLAlchemy, psycopg2-binary, Alembic, Celery, Redis, httpx, pydantic-settings y structlog. Calidad: Ruff (linter/formatter), pytest y pytest-asyncio.
- Frontend: Debe incluir React 18, TypeScript, Vite 5, Tailwind CSS 3, react-router-dom, axios y lucide-react. Calidad: ESLint, Prettier y Vitest.

## 5. Especificaciones de Infraestructura (Docker)
- PostgreSQL 15: Expuesto en puerto 5432, con variables de entorno para usuario, contraseña y base de datos, volumen persistente y healthcheck.
- Redis 7: Expuesto en puerto 6379, con volumen persistente y healthcheck.

## 6. Especificaciones de Configuración del Backend
- Variables de entorno: Archivo .env.example con plantillas para conexión a BD, Redis, Celery, API y logging.
- Endpoint de salud: Ruta /health que retorna un JSON indicando estado operativo.
- Puerto: Backend expuesto en el puerto **8000**.
- CORS: Configurado explícitamente para aceptar solicitudes desde el puerto del frontend (5173) en desarrollo.
- Celery: Configurado para usar Redis como broker y backend de resultados.

## 7. Especificaciones de Configuración del Frontend
- Puerto: Frontend servido en el puerto **5173**.
- Vite: Configurado con proxy para redirigir solicitudes de /api al backend local y /ws para WebSockets.
- Tailwind CSS: Inicializado y configurado para escanear los archivos de componentes.
- Interfaz: Una pantalla de bienvenida simple que confirme la inicialización correcta del sistema y un layout base con navegación preparada para futuros módulos.

## 8. Especificaciones del Script de Gestión (manage.py)
El script debe ser un archivo Python ejecutable en la raíz del proyecto que gestione el ciclo de vida local sin necesidad de comandos manuales dispersos. Debe implementar:
- setup: Verifica Python, Node.js y Docker. Instala dependencias de backend y frontend. Copia .env.example a .env si no existe. Inicializa el repositorio Git (`git init`) y realiza el commit inicial. Levanta la infraestructura Docker.
- start: Levanta Docker, luego inicia el backend, el worker de Celery y el frontend en segundo plano, guardando sus PIDs y redirigiendo la salida a archivos de log.
- stop: Lee los PIDs guardados, envía señales de terminación ordenada a los procesos, espera un tiempo prudencial, fuerza la terminación si es necesario, detiene Docker y limpia los archivos PID.
- restart: Ejecuta stop seguido de start.
- status: Verifica el estado de Docker y la existencia/actividad de los PIDs, mostrando un resumen visual con colores y las URLs de acceso.
- logs [servicio]: Muestra la salida en tiempo real de los archivos de log del servicio especificado (backend, celery, frontend) o de docker-compose.

## 9. Plan de Ejecución
1. Crear la estructura de directorios y archivos vacíos o con contenido mínimo.
2. Definir los archivos de dependencias (requirements.txt, package.json).
3. Configurar los archivos de entorno y docker-compose.yml.
4. Desarrollar el script manage.py con toda la lógica de gestión de procesos.
5. Implementar el endpoint de salud en el backend y la pantalla de bienvenida en el frontend.
6. Redactar los archivos README.md.
7. Probar el flujo completo de comandos del script de gestión.

## 10. Criterios de Finalización
La tarea se considera completada únicamente cuando se puede ejecutar `python manage.py setup` seguido de `python manage.py start`, y el comando `python manage.py status` reporta todos los servicios como activos, con el frontend y el backend accesibles en sus respectivos puertos, y el comando `stop` limpia todo el entorno sin dejar procesos huérfanos. Además, el repositorio Git debe estar inicializado con el commit inicial realizado por `setup`.

## 11. Restricciones
- No implementar lógica de negocio ni funcionalidad de importación real en esta tarea.
- No crear migraciones de base de datos ni tablas reales (se hará en la Tarea 2).
- No incluir código de implementación detallado en este documento, solo especificaciones de qué debe existir y cómo debe comportarse.