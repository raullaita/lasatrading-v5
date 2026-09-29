from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "LaSaTrading Backend"
    APP_VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"

    API_HOST: str = "127.0.0.1"
    API_PORT: int = 8000

    DATABASE_URL: str = "postgresql://lasa:lasa@localhost:5432/lasa"
    POSTGRES_USER: str = "lasa"
    POSTGRES_PASSWORD: str = "lasa"
    POSTGRES_DB: str = "lasa"

    REDIS_URL: str = "redis://localhost:6379/0"

    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    BINANCE_API_BASE_URL: str = "https://api.binance.com"
    BINANCE_SYMBOLS_CACHE_TTL: int = 86400
    BINANCE_THROTTLE_MS: int = 100
    BINANCE_MAX_RETRIES: int = 3
    BINANCE_RETRY_BACKOFF_BASE: float = 1.0
    BINANCE_429_RETRY_WAIT_SECONDS: int = 60
    BINANCE_REQUEST_TIMEOUT: float = 30.0
    BINANCE_KLINES_LIMIT: int = 1000

    CORS_ORIGINS: list[str] = ["http://localhost:5173"]

    # ---------------------------------------------------------------- alertas
    #: Interruptor maestro de Telegram. **Por defecto apagado**, y no por
    #: prudencia vaga: sin el, un test que instancia el servicio de alertas con un
    #: token real en el entorno mandaria avisos de operaciones al movil de quien
    #: escribio el test, y ese aviso ya no se borra. El modulo entero se puede
    #: tener desplegado sin que sends nada.
    TELEGRAM_ENABLED: bool = False
    #: Token del bot, del secreto que devuelve `@BotFather`. Vacio significa
    #: "no configurado", y el cliente falla con un mensaje util en vez de
    #: llamar a `api.telegram.org/bot/sendMessage` y recibir un 404 ilegible.
    TELEGRAM_BOT_TOKEN: str = ""
    #: Chat destino. **No se descubre solo**: un bot no puede escribir a alguien
    #: que no le haya escrito antes, asi que el valor sale de `getUpdates` despues
    #: de que el usuario mande `/start` al bot.
    TELEGRAM_CHAT_ID: str = ""
    #: Segundos entre mensajes al mismo chat. Telegram admite 1 por segundo y
    #: por chat, y devuelve 429 con `retry_after` cuando se pasa; este limite es
    #: el nuestro, para no gastar la cuota de la API discoveriendolo.
    TELEGRAM_MIN_INTERVAL_SECONDS: float = 1.0
    #: Intentos de entrega antes de dar la alerta por fallida. El 429 **no** cuenta
    #: como fallo de entrega: se respeta el `retry_after` y se reintenta, porque
    #: es una orden de la API y no un fallo nuestro.
    TELEGRAM_MAX_ATTEMPTS: int = 5
    #: Tope del mensaje, el limite de la API. Un mensaje mas largo se trunca y se
    #: marca, porque un mensaje cortado en mitad de un numero es peor que no
    #: enviado.
    TELEGRAM_MAX_MESSAGE_CHARS: int = 4096
    #: Cada cuanto el planificador evalua las reglas de alerta, en segundos.
    #:
    #: **300 s por defecto, y no 900.** El intervalo no es una cuestion de eficiencia
    #: sino de no perder avisos: entre dos evaluaciones pueden cerrarse hasta
    #: ``intervalo / duracion_vela`` velas, y las que ya se cerraron no estan en la
    #: ventana la siguiente vez. Con velas de 1 minuto y un evaluador cada 15
    #: minutos, un cruce de las 10:00 se ha ido de la ventana antes de que nadie
    #: mire a las 10:15, y no hay ningun error: simplemente no avisa nunca.
    #:
    #: Con velas de 1 hora, 5 minutos dan doce evaluaciones por vela y once son
    #: redundantes; el indice unico las para y la pre-comprobacion evita que
    #: gasten transacciones. Mirar de mas no cuesta, mirar de menos si.
    ALERTS_EVALUATE_SECONDS: int = 300


def get_settings() -> Settings:
    return Settings()
