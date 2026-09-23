import asyncio
import json
import time
from decimal import Decimal

import httpx
import redis.asyncio as aioredis
from pydantic import ValidationError

from app.config import get_settings
from app.modules.data_import.schemas import BinanceSymbolOut, CandleRaw


class BinanceClientError(Exception):
    pass


class BinanceClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._last_request_at: float | None = None
        self._client = httpx.AsyncClient(
            base_url=self.settings.BINANCE_API_BASE_URL,
            timeout=self.settings.BINANCE_REQUEST_TIMEOUT,
        )
        self._redis = aioredis.from_url(self.settings.REDIS_URL, decode_responses=True)

    async def close(self) -> None:
        await self._client.aclose()
        await self._redis.aclose()

    async def _throttle(self) -> None:
        now = time.monotonic()
        if self._last_request_at is not None:
            elapsed = now - self._last_request_at
            needed = self.settings.BINANCE_THROTTLE_MS / 1000.0
            if elapsed < needed:
                await asyncio.sleep(needed - elapsed)
        self._last_request_at = time.monotonic()

    def _backoff(self, attempt: int) -> float:
        return self.settings.BINANCE_RETRY_BACKOFF_BASE * (2 ** (attempt - 1))

    async def _get_json(self, path: str, params: dict | None = None) -> list | dict:
        retries = self.settings.BINANCE_MAX_RETRIES
        for attempt in range(1, retries + 1):
            try:
                await self._throttle()
                response = await self._client.get(path, params=params)
                if response.status_code == 429:
                    await asyncio.sleep(self.settings.BINANCE_429_RETRY_WAIT_SECONDS)
                    continue
                response.raise_for_status()
                return response.json()
            except httpx.TimeoutException as exc:
                if attempt >= retries:
                    raise BinanceClientError(
                        f"Timeout en request a Binance: {path}"
                    ) from exc
                await asyncio.sleep(self._backoff(attempt))
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code >= 500:
                    if attempt >= retries:
                        raise BinanceClientError(
                            f"Error 5xx de Binance en {path}: "
                            f"{exc.response.status_code}"
                        ) from exc
                    await asyncio.sleep(self._backoff(attempt))
                else:
                    raise BinanceClientError(
                        f"Error {exc.response.status_code} de Binance en {path}: "
                        f"{exc.response.text}"
                    ) from exc
            except httpx.TransportError as exc:
                if attempt >= retries:
                    raise BinanceClientError(
                        f"Error de red con Binance: {exc}"
                    ) from exc
                await asyncio.sleep(self._backoff(attempt))

    async def get_symbols(self) -> list[BinanceSymbolOut]:
        cache_key = "binance:symbols"
        cached = await self._redis.get(cache_key)
        if cached:
            return [BinanceSymbolOut(**item) for item in json.loads(cached)]
        data = await self._get_json("/api/v3/exchangeInfo")
        symbols = [
            BinanceSymbolOut(
                symbol=item["symbol"],
                status=item["status"],
                base_asset=item["baseAsset"],
                quote_asset=item["quoteAsset"],
            )
            for item in data["symbols"]
        ]
        await self._redis.set(
            cache_key,
            json.dumps([s.model_dump() for s in symbols]),
            ex=self.settings.BINANCE_SYMBOLS_CACHE_TTL,
        )
        return symbols

    async def get_klines(
        self,
        symbol: str,
        timeframe: str,
        start_ms: int,
        end_ms: int,
        limit: int | None = None,
    ) -> list[CandleRaw]:
        params = {
            "symbol": symbol,
            "interval": timeframe,
            "startTime": start_ms,
            "endTime": end_ms,
            "limit": limit or self.settings.BINANCE_KLINES_LIMIT,
        }
        data = await self._get_json("/api/v3/klines", params=params)
        candles = []
        for row in data:
            try:
                candles.append(
                    CandleRaw(
                        open_time_ms=int(row[0]),
                        close_time_ms=int(row[6]),
                        open=Decimal(row[1]),
                        high=Decimal(row[2]),
                        low=Decimal(row[3]),
                        close=Decimal(row[4]),
                        volume=Decimal(row[5]),
                        quote_volume=Decimal(row[7]),
                        num_trades=int(row[8]),
                    )
                )
            except (ValueError, IndexError, ValidationError) as exc:
                raise BinanceClientError(
                    f"Formato de kline inválido para {symbol} {timeframe}"
                ) from exc
        return candles
