from app.config import get_settings
from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.modules.alerts.service import AlertService


@celery_app.task(name="alerts.evaluate_rules")
def evaluate_alerts_task() -> None:
    """Evalúa todas las reglas activas y entrega lo que corresponda.

    Sin ``asyncio.run`` y sin ningún argumento, igual que ``run_backtest_task`` y
    ``run_walk_forward_task``: el servicio es síncrono a propósito y el planificador
    no tiene nada que pasarle.

    La ausencia de argumento **es** la idempotencia. La tarea no lleva ni el
    identificador de una pasada, así que ejecutarla dos veces seguidas no duplica
    nada: el índice único de ``alerts`` para el segundo intento y el enfriamiento
    de cada regla para el tercero. Es lo que hace que un ``beat_schedule`` mal
    configurado —o un worker con beat embebido y dos procesos— sea un despiste y
    no un incidente.
    """
    ajustes = get_settings()
    if not ajustes.TELEGRAM_ENABLED:
        # No se lanza la evaluación con el canal apagado. Escribir alertas que
        # nadie va a recibir solo llena la tabla de `skipped` y hace que el
        # historial deje de significar "qué ha pasado" para significar "qué ha
        # pasado o qué no se pudo entregar". Para diagnosticar el canal está el
        # endpoint de prueba, que es explícito.
        return
    with SessionLocal() as db:
        resumen = AlertService().evaluar_todas(
            db, intervalo_s=ajustes.ALERTS_EVALUATE_SECONDS
        )
    if resumen.detecciones or resumen.errores:
        # Solo se escribe cuando hay algo que contar. Una linea por cada cinco
        # minutos con «0 detecciones» llena el log del ruido que esconde justo
        # los mensajes de error, que son los que se van a buscar.
        import structlog

        structlog.get_logger("alerts").info(
            "alertas evaluadas",
            evaluadas=resumen.evaluadas,
            detecciones=resumen.detecciones,
            avisadas=resumen.avisadas,
            duplicadas=resumen.duplicadas,
            omitidas=resumen.omitidas_enfriamiento,
            errores=resumen.errores,
            notas=list(resumen.notas)[:5],
        )
