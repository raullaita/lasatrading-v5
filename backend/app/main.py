import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.modules.alerts import (
    models as _alerts_models,  # noqa: F401  # metadata Alembic
)
from app.modules.alerts.router import router as alerts_router
from app.modules.backtesting import (
    models as _backtesting_models,  # noqa: F401  # metadata Alembic
)
from app.modules.backtesting.router import router as backtesting_router
from app.modules.backtesting.walk_forward_router import (
    router as walk_forward_router,
)
from app.modules.data.router import router as data_router
from app.modules.data_import import (
    models as _data_import_models,  # noqa: F401  # metadata Alembic
)
from app.modules.data_import.router import router as data_import_router
from app.modules.features import (
    models as _features_models,  # noqa: F401  # metadata Alembic
)
from app.modules.features.router import router as features_router
from app.modules.patterns import (
    models as _patterns_models,  # noqa: F401  # metadata Alembic
)
from app.modules.patterns.router import router as patterns_router

settings = get_settings()

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ],
)

logger = structlog.get_logger()

app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(data_import_router)
app.include_router(data_router)
app.include_router(features_router)
app.include_router(patterns_router)
app.include_router(alerts_router)
app.include_router(backtesting_router)
app.include_router(walk_forward_router)


@app.get("/health")
def health() -> dict:
    logger.info("health_check")
    return {
        "status": "ok",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }
