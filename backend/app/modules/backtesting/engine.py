"""Motor de backtesting: simula una estrategia sobre las ocurrencias detectadas.

Reglas del modulo (no negociables):

* Prohibido ``iterrows()``, ``itertuples()`` y cualquier bucle **sobre velas**.
  El bucle que existe es sobre *senales*, que es inevitable: una estrategia con
  una sola posicion abierta es intrinsecamente secuencial, porque la entrada de
  la senal N depende de donde salio la N-1. Lo que no se admite es que ese bucle
  se desmonte en iteraciones por vela, y no lo hace: la busqueda de salida y el
  mark-to-market de cada operacion son operaciones de ``numpy`` sobre la ventana
  de velas de la operacion.

* Sin lookahead. La senal se conoce en el **cierre** de la vela T, asi que la
  entrada mas temprana posible es la **apertura de T+1** (``entry_offset``). Nunca
  al cierre de T.

* Ante la duda, el peor caso. Si en la misma vela se tocan take profit y stop
  loss, sin datos intrabar no se sabe cual ocurrio antes, y asumir el mejor
  produce estrategias que en vivo no funcionan. Se asume el stop loss.

* ``end_of_data`` no es un resultado de la estrategia, es la falta de velas
  posteriores para cerrar. Se contabiliza aparte y se excluye de ``win_rate`` y
  ``profit_factor``; mezclarlo ahi rebajaria el acierto por un motivo que no es
  del patron.

Convencion de entrada: las velas llegan como las produce
``app.modules.data.candles.load_candles`` (indice UTC monotono, OHLCV en
float64) y las senales como un DataFrame con columnas ``timestamp``,
``pattern_name`` y ``direction``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

#: 4 puntos basicos por lado, el taker habitual en exchanges cripto.
DEFAULT_FEE_BPS = 4.0

#: Direccion de la posicion segun la direccion del patron.
LONG = "long"
SHORT = "short"

_BULLISH = "bullish"
_BEARISH = "bearish"

TAKE_PROFIT = "take_profit"
STOP_LOSS = "stop_loss"
TIMEOUT = "timeout"
END_OF_DATA = "end_of_data"

#: Motivos que cuentan como resultado de la estrategia. ``END_OF_DATA`` queda
#: fuera a proposito: ver la nota del docstring del modulo.
_COUNTED_REASONS = (TAKE_PROFIT, STOP_LOSS, TIMEOUT)


class StrategyError(ValueError):
    """Configuracion de estrategia invalida. Se falla antes de simular nada."""


@dataclass(frozen=True)
class StrategyConfig:
    """Parametros de la simulacion.

    ``take_profit_pct`` y ``stop_loss_pct`` van en porcentaje, no en fraccion:
    ``2.0`` es un 2%. Es la convencion que ya usan los parametros del catalogo
    de patrones y evita el error de escribir ``0.02`` donde se esperaba ``2``.

    ``max_hold`` es el numero maximo de velas que se mantiene la posicion,
    contando la vela de entrada. Con ``max_hold=1`` la posicion se cierra al
    cierre de la propia vela de entrada.
    """

    take_profit_pct: float | None = 2.0
    stop_loss_pct: float | None = 1.0
    max_hold: int = 24
    fee_bps: float = DEFAULT_FEE_BPS
    initial_capital: float = 1000.0
    use_fraction: float = 1.0
    entry_offset: int = 1
    allow_short: bool = True

    def __post_init__(self) -> None:
        if self.max_hold < 1:
            raise StrategyError(f"max_hold debe ser >= 1, recibio {self.max_hold}")
        if self.entry_offset < 1:
            raise StrategyError(
                "entry_offset debe ser >= 1: con 0 seria lookahead, se "
                "entraria en la vela de la senal usando su cierre, que "
                "todavia no se conoce"
            )
        if self.initial_capital <= 0:
            raise StrategyError("initial_capital debe ser > 0")
        if not 0 < self.use_fraction <= 1:
            raise StrategyError("use_fraction debe estar en (0, 1]")
        for name in ("take_profit_pct", "stop_loss_pct"):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise StrategyError(f"{name} debe ser > 0 o None")
        if self.take_profit_pct is None and self.stop_loss_pct is None:
            raise StrategyError(
                "Sin take_profit_pct ni stop_loss_pct no hay forma de cerrar la "
                "posicion antes que max_hold: la estrategia solo tendria "
                "timeouts"
            )
        if self.fee_bps < 0:
            raise StrategyError("fee_bps no puede ser negativo")

    def as_dict(self) -> dict:
        """Configuracion como JSONB, para guardarla congelada en el run."""
        return {
            "take_profit_pct": self.take_profit_pct,
            "stop_loss_pct": self.stop_loss_pct,
            "max_hold": self.max_hold,
            "fee_bps": self.fee_bps,
            "initial_capital": self.initial_capital,
            "use_fraction": self.use_fraction,
            "entry_offset": self.entry_offset,
            "allow_short": self.allow_short,
        }


@dataclass
class TradeResult:
    """Una operacion simulada, con suAccounting completo."""

    signal_timestamp: pd.Timestamp
    pattern_name: str
    direction: str
    entry_timestamp: pd.Timestamp
    entry_price: float
    exit_timestamp: pd.Timestamp | None
    exit_price: float | None
    exit_reason: str | None
    quantity: float
    gross_pnl: float | None
    fees: float
    net_pnl: float | None
    return_pct: float | None
    bars_held: int
    equity_after: float | None
    mae: float | None = None
    mfe: float | None = None


@dataclass
class BacktestResult:
    trades: list[TradeResult] = field(default_factory=list)
    #: Columna de equity por vela del rango simulado, con el drawdown ya
    #: calculado respecto al maximo alcanzado hasta esa vela.
    equity: pd.DataFrame | None = None
    metrics: dict = field(default_factory=dict)
    skipped_signals: int = 0
    truncated_signals: int = 0


def run_backtest(
    candles: pd.DataFrame,
    signals: pd.DataFrame,
    config: StrategyConfig,
) -> BacktestResult:
    """Simula la estrategia sobre ``signals`` usando ``candles`` como mercado.

    ``candles`` indexado por ``timestamp`` UTC y monotono (ver
    ``app.modules.data.candles``). ``signals`` con columnas ``timestamp``,
    ``pattern_name`` y ``direction``; se ordenan aqui, no se exige que lleguen
    ordenados.
    """
    _validate_frames(candles, signals)
    result = BacktestResult()
    if candles.empty or signals.empty:
        result.equity = _empty_equity(candles, config.initial_capital)
        result.metrics = _metrics([], result.equity, config)
        return result

    index = candles.index
    opens = candles["open"].to_numpy(dtype=float)
    highs = candles["high"].to_numpy(dtype=float)
    lows = candles["low"].to_numpy(dtype=float)
    closes = candles["close"].to_numpy(dtype=float)
    n = len(index)

    # Primer indice cuya vela abre **despues** de que la senal fuese conocida.
    # ``side="right"`` cubre los dos casos con una sola regla: si la senal
    # coincide con el cierre de una vela, la siguiente abre en T+1; si cae a
    # mitad de otra, su open ya paso y la siguiente es la primera posible.
    # Con ``side="left"`` mas uno, las señales intrabar entrarian una vela tarde.
    signal_ts = pd.DatetimeIndex(signals["timestamp"])
    entry_positions = index.searchsorted(signal_ts, side="right") + (
        config.entry_offset - 1
    )

    ordered = signals.assign(_entry=entry_positions).sort_values(
        ["_entry", "timestamp"], kind="stable"
    )
    patterns = ordered["pattern_name"].to_numpy()
    directions = ordered["direction"].to_numpy()

    curve = np.full(n, config.initial_capital, dtype=float)
    equity = config.initial_capital
    free_from = 0
    fee_rate = config.fee_bps / 10_000

    for position, pattern, direction in zip(
        ordered["_entry"].to_numpy(), patterns, directions, strict=True
    ):
        entry_idx = int(position)

        if entry_idx >= n:
            # La senal cae en las ultimas velas: no hay ninguna despues donde
            # entrar. No es una operacion truncada, es una senal no simulable.
            result.truncated_signals += 1
            continue

        long_side = direction == _BULLISH
        if not long_side and not config.allow_short:
            result.skipped_signals += 1
            continue
        if entry_idx < free_from:
            # Ya hay una posicion abierta que no se ha cerrado: una sola a la vez.
            result.skipped_signals += 1
            continue

        entry_price = float(opens[entry_idx])
        # El segundo caso peisimo de la vela: si el stop loss se toco en la vela
        # de entrada, se asume que ocurrio antes que cualquier otra cosa.
        if not long_side and config.stop_loss_pct is not None:
            entry_stop = entry_price * (1 + config.stop_loss_pct / 100)
            if highs[entry_idx] >= entry_stop:
                result.skipped_signals += 1
                continue

        available = n - entry_idx
        search_len = min(config.max_hold, available)
        window_slice = slice(entry_idx, entry_idx + search_len)

        # El nivel que cierra con beneficio y el que cierra con perdida estan a
        # lados opuestos segun la direccion, y lo mismo su condicion de
        # disparo. En un corto el stop esta por encima de la entrada y lo cruza
        # el maximo; calcularlo como en el largo daria un nivel por debajo del
        # precio, que cualquier vela tocaria, y cerraria todos los cortos en la
        # primera vela.
        if long_side:
            tp_level = (
                entry_price * (1 + config.take_profit_pct / 100)
                if config.take_profit_pct is not None
                else None
            )
            sl_level = (
                entry_price * (1 - config.stop_loss_pct / 100)
                if config.stop_loss_pct is not None
                else None
            )
            tp_hit = highs[window_slice] >= tp_level if tp_level is not None else None
            sl_hit = lows[window_slice] <= sl_level if sl_level is not None else None
        else:
            tp_level = (
                entry_price * (1 - config.take_profit_pct / 100)
                if config.take_profit_pct is not None
                else None
            )
            sl_level = (
                entry_price * (1 + config.stop_loss_pct / 100)
                if config.stop_loss_pct is not None
                else None
            )
            tp_hit = lows[window_slice] <= tp_level if tp_level is not None else None
            sl_hit = highs[window_slice] >= sl_level if sl_level is not None else None

        triggered = (
            (tp_hit | sl_hit)
            if tp_hit is not None and sl_hit is not None
            else (tp_hit if tp_hit is not None else sl_hit)
        )
        exit_offset = (
            int(np.argmax(triggered))
            if triggered is not None and triggered.any()
            else None
        )

        if exit_offset is not None:
            if sl_hit is not None and sl_hit[exit_offset]:
                # Peor caso: si ambos se tocaron en la misma vela, el stop loss.
                exit_reason, exit_price = STOP_LOSS, float(sl_level)
            else:
                exit_reason, exit_price = TAKE_PROFIT, float(tp_level)
        elif search_len == config.max_hold:
            exit_reason = TIMEOUT
            exit_price = float(closes[entry_idx + search_len - 1])
        else:
            # Se acabaron las velas antes de llegar a ``max_hold`` y sin tocar
            # ningun nivel: no se puede saber como habria terminado.
            exit_reason, exit_price = END_OF_DATA, float(closes[n - 1])

        exit_idx = entry_idx + (
            exit_offset if exit_offset is not None else search_len - 1
        )
        quantity = equity * config.use_fraction / entry_price
        entry_fee = quantity * entry_price * fee_rate
        exit_fee = quantity * exit_price * fee_rate
        fees = entry_fee + exit_fee

        delta = (exit_price - entry_price) * quantity
        gross = delta if long_side else -delta
        net = gross - fees
        equity += net

        held_slice = slice(entry_idx, exit_idx + 1)
        held_lows, held_highs = lows[held_slice], highs[held_slice]
        if long_side:
            mae = float(held_lows.min() / entry_price - 1)
            mfe = float(held_highs.max() / entry_price - 1)
        else:
            mae = float(1 - held_highs.max() / entry_price)
            mfe = float(1 - held_lows.min() / entry_price)

        # Mark-to-market: entre la entrada y la salida la curva no se queda
        # plana. Sin esto el drawdown de una posicion que se va 5% en contra no
        # apareceria hasta el cierre, y el max_drawdown subestimaria el riesgo
        # real de la estrategia.
        held_closes = closes[held_slice]
        unrealized = (
            (held_closes - entry_price) * quantity
            if long_side
            else (entry_price - held_closes) * quantity
        )
        if entry_idx > free_from:
            curve[free_from:entry_idx] = equity - net
        curve[held_slice] = equity - net + unrealized - entry_fee
        # La vela de salida se fija al PnL realizado y no al mark-to-market de
        # su cierre: la salida ocurrio en el nivel TP/SL a mitad de vela, y anclar
        # al cierre dejaria un salto artificial en el punto donde la curva tiene
        # que ser exacta.
        curve[exit_idx] = equity

        result.trades.append(
            TradeResult(
                signal_timestamp=index[entry_idx - config.entry_offset],
                pattern_name=str(pattern),
                direction=LONG if long_side else SHORT,
                entry_timestamp=index[entry_idx],
                entry_price=entry_price,
                exit_timestamp=index[exit_idx],
                exit_price=exit_price,
                exit_reason=exit_reason,
                quantity=quantity,
                gross_pnl=gross,
                fees=fees,
                net_pnl=net,
                return_pct=net / (quantity * entry_price) * 100,
                bars_held=exit_idx - entry_idx + 1,
                equity_after=equity,
                mae=mae,
                mfe=mfe,
            )
        )
        free_from = exit_idx + 1

    if free_from < n:
        curve[free_from:] = equity

    result.equity = _build_equity(index, curve)
    result.metrics = _metrics(result.trades, result.equity, config)
    return result


def _validate_frames(candles: pd.DataFrame, signals: pd.DataFrame) -> None:
    if not candles.index.is_monotonic_increasing:
        raise StrategyError("El indice de velas no es monotono creciente")
    if not isinstance(candles.index, pd.DatetimeIndex):
        raise StrategyError("El indice de velas debe ser un DatetimeIndex")
    for column in ("open", "high", "low", "close"):
        if column not in candles.columns:
            raise StrategyError(f"Falta la columna {column} en las velas")
    if not signals.empty:
        missing = {"timestamp", "pattern_name", "direction"} - set(signals.columns)
        if missing:
            raise StrategyError(f"Faltan columnas en las senales: {sorted(missing)}")
        bad = set(signals["direction"].unique()) - {_BULLISH, _BEARISH}
        if bad:
            raise StrategyError(f"Direcciones no soportadas: {sorted(bad)}")


def _empty_equity(candles: pd.DataFrame, capital: float) -> pd.DataFrame:
    if candles.empty:
        return pd.DataFrame(
            {
                "equity": pd.Series(dtype=float),
                "drawdown_pct": pd.Series(dtype=float),
            },
            index=pd.DatetimeIndex([], tz="UTC", name="timestamp"),
        )
    return _build_equity(
        candles.index, np.full(len(candles), float(capital), dtype=float)
    )


def _build_equity(index: pd.DatetimeIndex, curve: np.ndarray) -> pd.DataFrame:
    peak = np.maximum.accumulate(curve)
    with np.errstate(divide="ignore", invalid="ignore"):
        drawdown = np.where(peak > 0, (peak - curve) / peak * 100, 0.0)
    return pd.DataFrame(
        {"equity": curve, "drawdown_pct": drawdown}, index=index
    ).rename_axis("timestamp")


def _metrics(
    trades: Sequence[TradeResult],
    equity: pd.DataFrame,
    config: StrategyConfig,
) -> dict:
    """Metricas del run.

    ``win_rate`` y ``profit_factor`` se calculan **solo** sobre las operaciones
    con motivo contado; las truncadas por falta de velas se excluyen, tal como
    se documento en el modulo. Se expone ademas ``trades_evaluated`` para que la
    UI pueda decir "12 de 14" en vez de dar un porcentaje sin contexto.

    ``profit_factor`` sale a ``None`` cuando no hay ninguna perdedora: la razon
    es infinita y JSONB no puede almacenar infinito. No se confunde con "sin
    datos", porque en ese caso ``trades_evaluated`` viene a cero.
    """
    counted = [t for t in trades if t.exit_reason in _COUNTED_REASONS]
    wins = [t for t in counted if (t.net_pnl or 0) > 0]
    losses = [t for t in counted if (t.net_pnl or 0) < 0]

    gross_gain = sum(t.net_pnl for t in wins if t.net_pnl)
    gross_loss = -sum(t.net_pnl for t in losses if t.net_pnl)

    equity_final = (
        float(equity["equity"].iloc[-1]) if len(equity) else config.initial_capital
    )
    return_pct = (equity_final / config.initial_capital - 1) * 100

    bars = [t.bars_held for t in counted]
    return {
        "initial_capital": config.initial_capital,
        "equity_final": equity_final,
        "net_pnl": equity_final - config.initial_capital,
        "total_return_pct": return_pct,
        "total_trades": len(trades),
        "trades_evaluated": len(counted),
        "win_rate": len(wins) / len(counted) if counted else None,
        "profit_factor": (gross_gain / gross_loss) if gross_loss > 0 else None,
        "max_drawdown_pct": (
            float(equity["drawdown_pct"].max()) if len(equity) else 0.0
        ),
        "avg_bars_held": (sum(bars) / len(bars)) if bars else None,
        "sharpe_ratio": _sharpe(equity),
    }


def _sharpe(equity: pd.DataFrame) -> float | None:
    """Sharpe de los retornos por vela, anualizado con la mediana del intervalo.

    Se anualiza con la frecuencia **infernada de los datos** (mediana de la
    separacion entre velas) y no con un diccionario de timeframes: asi el
    calculo sigue siendo correcto si se simula sobre un timeframe nuevo sin
    tocar el motor. Con menos de 3 velas no hay varianza que estimar.
    """
    if len(equity) < 3:
        return None
    values = equity["equity"].to_numpy(dtype=float)
    returns = np.diff(values) / values[:-1]
    if returns.size < 2:
        return None
    std = returns.std(ddof=1)
    if std == 0:
        return None
    periods_per_year = 365.0 * 24 * 3600.0
    index = equity.index
    deltas = np.diff(index.view("int64"))
    if deltas.size == 0 or deltas.min() <= 0:
        return None
    return float(returns.mean() / std * np.sqrt(periods_per_year / np.median(deltas)))
