
"""
SMC V3 — Strict, auditable ICT/SMC-inspired signal engine.

Historical-testing engine only. Does not connect to an account or place trades.

Required sequence:
1. D1 and H4 structure bias agree.
2. Price is in discount for CALL or premium for PUT.
3. A CLOSED M15 candle raids prior liquidity and closes back across the level.
4. After the M15 candle has closed, M1 confirms MSS.
5. A later M1 displacement candle creates a valid FVG.
6. The last opposing candle before displacement is the candidate OB.
7. FVG and OB overlap.
8. A subsequent M1 candle retraces into the overlap and confirms direction.
9. Entry is the observed next M1 candle open.

Only use candles available at the historical decision time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence


VERSION = "3.1.0"

SWING_LEFT = 2
SWING_RIGHT = 2
HTF_LOOKBACK = 80
RANGE_LOOKBACK = 40
LIQUIDITY_LOOKBACK = 20
MSS_LOOKBACK = 12
DISPLACEMENT_LOOKBACK = 20
ATR_PERIOD = 14
MIN_DISPLACEMENT_ATR = 1.0
MIN_FVG_ATR = 0.05
MAX_FVG_ATR = 1.5
MAX_RETRACE_DISTANCE_ATR = 0.35

M1_SECONDS = 60
M15_SECONDS = 900


@dataclass(frozen=True)
class Candle:
    epoch: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def valid(self) -> bool:
        values = (self.open, self.high, self.low, self.close, self.volume)
        if not all(isinstance(v, (int, float)) for v in values):
            return False
        if not all(_finite(v) for v in values):
            return False
        if not isinstance(self.epoch, int) or self.epoch < 0:
            return False
        if min(self.open, self.high, self.low, self.close) <= 0:
            return False
        return (
            self.high >= max(self.open, self.close, self.low)
            and self.low <= min(self.open, self.close, self.high)
            and self.volume >= 0
        )


@dataclass(frozen=True)
class Zone:
    low: float
    high: float
    kind: str
    epoch: int

    def overlaps(self, other: "Zone") -> bool:
        return max(self.low, other.low) <= min(self.high, other.high)

    def contains(self, price: float) -> bool:
        return self.low <= price <= self.high

    @property
    def midpoint(self) -> float:
        return (self.low + self.high) / 2.0


@dataclass(frozen=True)
class SignalResult:
    signal: str
    reason: str
    entry_epoch: Optional[int] = None
    entry_price: Optional[float] = None
    htf_bias: str = "NEUTRAL"
    liquidity_type: str = ""
    sweep_level: Optional[float] = None
    mss_level: Optional[float] = None
    displacement_atr: Optional[float] = None
    fvg: Optional[Zone] = None
    order_block: Optional[Zone] = None
    premium_discount: str = ""
    details: Optional[dict[str, Any]] = None

    def as_dict(self) -> dict[str, Any]:
        def zone_dict(zone: Optional[Zone]) -> Optional[dict[str, Any]]:
            if zone is None:
                return None
            return {
                "low": zone.low,
                "high": zone.high,
                "kind": zone.kind,
                "epoch": zone.epoch,
            }

        return {
            "version": VERSION,
            "signal": self.signal,
            "reason": self.reason,
            "entry_epoch": self.entry_epoch,
            "entry_price": self.entry_price,
            "htf_bias": self.htf_bias,
            "liquidity_type": self.liquidity_type,
            "sweep_level": self.sweep_level,
            "mss_level": self.mss_level,
            "displacement_atr": self.displacement_atr,
            "fvg": zone_dict(self.fvg),
            "order_block": zone_dict(self.order_block),
            "premium_discount": self.premium_discount,
            "details": self.details or {},
        }


def _finite(value: float) -> bool:
    try:
        return value == value and abs(value) != float("inf")
    except (TypeError, ValueError):
        return False


def _no_signal(reason: str, **kwargs: Any) -> SignalResult:
    return SignalResult(
        signal="NO_SIGNAL",
        reason=reason,
        details=kwargs,
    )


def _validate_candles(
    candles: Sequence[Candle],
    name: str,
) -> Optional[str]:
    if not candles:
        return f"{name}: no candles supplied"

    previous_epoch = -1
    for candle in candles:
        if not isinstance(candle, Candle) or not candle.valid():
            return f"{name}: invalid candle"
        if candle.epoch <= previous_epoch:
            return f"{name}: candles must be ordered by unique ascending epoch"
        previous_epoch = candle.epoch

    return None


def _true_ranges(candles: Sequence[Candle]) -> list[float]:
    ranges: list[float] = []
    previous_close: Optional[float] = None

    for candle in candles:
        if previous_close is None:
            value = candle.high - candle.low
        else:
            value = max(
                candle.high - candle.low,
                abs(candle.high - previous_close),
                abs(candle.low - previous_close),
            )
        ranges.append(value)
        previous_close = candle.close

    return ranges


def atr(
    candles: Sequence[Candle],
    period: int = ATR_PERIOD,
) -> Optional[float]:
    """Mean true range over the latest period candles."""
    if period <= 0 or len(candles) < period:
        return None

    values = _true_ranges(candles[-period:])
    result = sum(values) / len(values)
    return result if result > 0 else None


def swing_highs(
    candles: Sequence[Candle],
    left: int = SWING_LEFT,
    right: int = SWING_RIGHT,
) -> list[int]:
    """Indices of confirmed swing highs; right-side candles are required."""
    if left < 1 or right < 1:
        return []

    result: list[int] = []
    for i in range(left, len(candles) - right):
        current = candles[i].high
        neighbours = (
            [candles[j].high for j in range(i - left, i)]
            + [candles[j].high for j in range(i + 1, i + right + 1)]
        )
        if all(current > value for value in neighbours):
            result.append(i)

    return result


def swing_lows(
    candles: Sequence[Candle],
    left: int = SWING_LEFT,
    right: int = SWING_RIGHT,
) -> list[int]:
    """Indices of confirmed swing lows; right-side candles are required."""
    if left < 1 or right < 1:
        return []

    result: list[int] = []
    for i in range(left, len(candles) - right):
        current = candles[i].low
        neighbours = (
            [candles[j].low for j in range(i - left, i)]
            + [candles[j].low for j in range(i + 1, i + right + 1)]
        )
        if all(current < value for value in neighbours):
            result.append(i)

    return result


def _structure_bias(candles: Sequence[Candle]) -> str:
    """
    BULLISH: last two confirmed swing highs and lows are rising.
    BEARISH: last two confirmed swing highs and lows are falling.
    Otherwise NEUTRAL.
    """
    if len(candles) < max(HTF_LOOKBACK, SWING_LEFT + SWING_RIGHT + 10):
        return "NEUTRAL"

    data = candles[-HTF_LOOKBACK:]
    highs = swing_highs(data)
    lows = swing_lows(data)

    if len(highs) < 2 or len(lows) < 2:
        return "NEUTRAL"

    h1 = data[highs[-2]].high
    h2 = data[highs[-1]].high
    l1 = data[lows[-2]].low
    l2 = data[lows[-1]].low

    if h2 > h1 and l2 > l1:
        return "BULLISH"
    if h2 < h1 and l2 < l1:
        return "BEARISH"
    return "NEUTRAL"


def _dealing_range(
    candles: Sequence[Candle],
) -> tuple[float, float, float]:
    data = candles[-RANGE_LOOKBACK:]
    high = max(c.high for c in data)
    low = min(c.low for c in data)
    return low, high, (high + low) / 2.0


def _premium_discount(
    price: float,
    low: float,
    high: float,
) -> str:
    midpoint = (low + high) / 2.0
    if price < midpoint:
        return "DISCOUNT"
    if price > midpoint:
        return "PREMIUM"
    return "EQUILIBRIUM"


def _find_liquidity_raid(
    candles: Sequence[Candle],
    bias: str,
) -> Optional[tuple[str, float, int]]:
    """
    Return (liquidity type, swept level, raid index).
    Each level is calculated only from candles preceding its raid candle.
    """
    minimum = LIQUIDITY_LOOKBACK + SWING_LEFT + SWING_RIGHT + 2
    if len(candles) < minimum:
        return None

    start = max(0, len(candles) - 8)

    for i in range(len(candles) - 1, start - 1, -1):
        prior = candles[:i]
        window = prior[-LIQUIDITY_LOOKBACK:]
        if len(window) < LIQUIDITY_LOOKBACK:
            continue

        raid = candles[i]

        if bias == "BULLISH":
            indices = swing_lows(window)
            if not indices:
                continue
            level = window[indices[-1]].low
            if raid.low < level and raid.close > level:
                return "SSL", level, i

        elif bias == "BEARISH":
            indices = swing_highs(window)
            if not indices:
                continue
            level = window[indices[-1]].high
            if raid.high > level and raid.close < level:
                return "BSL", level, i

    return None


def _mss_level(
    candles: Sequence[Candle],
    direction: str,
) -> Optional[float]:
    """Latest confirmed internal swing in the supplied pre-MSS candles."""
    if len(candles) < MSS_LOOKBACK + SWING_LEFT + SWING_RIGHT:
        return None

    window = candles[-MSS_LOOKBACK:]

    if direction == "BULLISH":
        indices = swing_highs(window)
        return window[indices[-1]].high if indices else None

    indices = swing_lows(window)
    return window[indices[-1]].low if indices else None


def _displacement(
    candle: Candle,
    direction: str,
    baseline_atr: float,
) -> tuple[bool, float]:
    """Directional candle body must meet the configured ATR threshold."""
    if baseline_atr <= 0:
        return False, 0.0

    body = abs(candle.close - candle.open)
    ratio = body / baseline_atr
    directional = (
        candle.close > candle.open
        if direction == "BULLISH"
        else candle.close < candle.open
    )

    return directional and ratio >= MIN_DISPLACEMENT_ATR, ratio


def _find_fvg(
    candles: Sequence[Candle],
    direction: str,
    baseline_atr: float,
) -> Optional[Zone]:
    """Find a three-candle FVG ending at the last supplied candle."""
    if len(candles) < 3 or baseline_atr <= 0:
        return None

    first, middle, third = candles[-3], candles[-2], candles[-1]

    if direction == "BULLISH":
        low, high = first.high, third.low
        if high <= low or middle.close <= middle.open:
            return None
    else:
        low, high = third.high, first.low
        if high <= low or middle.close >= middle.open:
            return None

    size_ratio = (high - low) / baseline_atr
    if not MIN_FVG_ATR <= size_ratio <= MAX_FVG_ATR:
        return None

    return Zone(
        low=low,
        high=high,
        kind=f"{direction}_FVG",
        epoch=third.epoch,
    )


def _find_order_block(
    candles: Sequence[Candle],
    direction: str,
    displacement_index: int,
) -> Optional[Zone]:
    """
    Find the last opposing candle before displacement.
    This is a reproducible candidate zone, not proof of institutional orders.
    """
    start = max(0, displacement_index - 5)

    for i in range(displacement_index - 1, start - 1, -1):
        candle = candles[i]
        opposing = (
            candle.close < candle.open
            if direction == "BULLISH"
            else candle.close > candle.open
        )

        if opposing:
            return Zone(
                low=candle.low,
                high=candle.high,
                kind=f"{direction}_OB_CANDIDATE",
                epoch=candle.epoch,
            )

    return None


def _zone_touch(candle: Candle, zone: Zone) -> bool:
    return candle.low <= zone.high and candle.high >= zone.low


def evaluate_smc_v3(
    d1: Sequence[Candle],
    h4: Sequence[Candle],
    m15: Sequence[Candle],
    m1: Sequence[Candle],
) -> SignalResult:
    """
    Evaluate a snapshot using CLOSED candles only.

    The latest M1 candle is the decision/confirmation candle. The M15 raid
    candle must have closed before any M1 MSS candle can be considered.

    To avoid lookahead bias, the caller must supply only candles that were
    closed and available at the decision time.
    """
    for name, data in (
        ("D1", d1),
        ("H4", h4),
        ("M15", m15),
        ("M1", m1),
    ):
        error = _validate_candles(data, name)
        if error:
            return _no_signal(error)

    if len(d1) < HTF_LOOKBACK or len(h4) < HTF_LOOKBACK:
        return _no_signal("Insufficient D1/H4 history for strict bias")

    if len(h4) < RANGE_LOOKBACK:
        return _no_signal("Insufficient H4 history for dealing range")

    if len(m15) < LIQUIDITY_LOOKBACK + 10:
        return _no_signal("Insufficient M15 history")

    if len(m1) < max(ATR_PERIOD + 5, MSS_LOOKBACK + 8):
        return _no_signal("Insufficient M1 history")

    # Ensure the latest D1/H4/M15 candles have closed by the latest M1 close.
    decision_close = m1[-1].epoch + M1_SECONDS
    if d1[-1].epoch + 86400 > decision_close:
        return _no_signal("Latest D1 candle is not closed at decision time")
    if h4[-1].epoch + 14400 > decision_close:
        return _no_signal("Latest H4 candle is not closed at decision time")
    if m15[-1].epoch + M15_SECONDS > decision_close:
        return _no_signal("Latest M15 candle is not closed at decision time")

    # 1. D1/H4 structural agreement.
    d1_bias = _structure_bias(d1)
    h4_bias = _structure_bias(h4)

    if d1_bias == "NEUTRAL" or h4_bias == "NEUTRAL":
        return _no_signal(
            "D1 or H4 bias is neutral",
            d1_bias=d1_bias,
            h4_bias=h4_bias,
        )

    if d1_bias != h4_bias:
        return _no_signal(
            "D1/H4 bias disagreement",
            d1_bias=d1_bias,
            h4_bias=h4_bias,
        )

    direction = d1_bias

    # 2. Premium/discount using the latest closed H4 dealing range.
    range_low, range_high, midpoint = _dealing_range(h4)
    location = _premium_discount(h4[-1].close, range_low, range_high)

    if direction == "BULLISH" and location != "DISCOUNT":
        return _no_signal(
            "Bullish bias requires discount location",
            htf_bias=direction,
            premium_discount=location,
            dealing_range=(range_low, range_high),
        )

    if direction == "BEARISH" and location != "PREMIUM":
        return _no_signal(
            "Bearish bias requires premium location",
            htf_bias=direction,
            premium_discount=location,
            dealing_range=(range_low, range_high),
        )

    # 3. Most recent qualifying M15 liquidity raid.
    raid = _find_liquidity_raid(m15, direction)
    if raid is None:
        return _no_signal(
            "No qualifying M15 liquidity raid",
            htf_bias=direction,
            premium_discount=location,
        )

    liquidity_type, sweep_level, raid_index = raid
    raid_candle = m15[raid_index]
    raid_close_epoch = raid_candle.epoch + M15_SECONDS

    # M1 candles must start no earlier than the M15 close.
    post_raid = [
        candle for candle in m1
        if candle.epoch >= raid_close_epoch
    ]

    if len(post_raid) < MSS_LOOKBACK + ATR_PERIOD + 4:
        return _no_signal(
            "Insufficient M1 history after the closed M15 raid",
            htf_bias=direction,
            liquidity_type=liquidity_type,
            sweep_level=sweep_level,
            raid_close_epoch=raid_close_epoch,
        )

    # 4. Search for a confirmed MSS on a closed M1 candle.
    # Each MSS level is built from earlier candles, not the MSS candle itself.
    mss_index: Optional[int] = None
    mss_level: Optional[float] = None

    for i in range(MSS_LOOKBACK + SWING_LEFT + SWING_RIGHT, len(post_raid)):
        level = _mss_level(post_raid[:i], direction)
        if level is None:
            continue

        candle = post_raid[i]
        crossed = (
            candle.close > level
            if direction == "BULLISH"
            else candle.close < level
        )

        if crossed:
            mss_index = i
            mss_level = level
            break

    if mss_index is None or mss_level is None:
        return _no_signal(
            "No M1 MSS after the closed M15 raid",
            htf_bias=direction,
            liquidity_type=liquidity_type,
            sweep_level=sweep_level,
            raid_close_epoch=raid_close_epoch,
        )

    # 5. A later displacement candle must also form a valid FVG.
    displacement_index: Optional[int] = None
    displacement_ratio: Optional[float] = None
    fvg: Optional[Zone] = None
    baseline_atr: Optional[float] = None

    for i in range(mss_index + 1, len(post_raid)):
        prior = post_raid[:i]
        baseline = atr(prior, ATR_PERIOD)
        if baseline is None:
            continue

        ok, ratio = _displacement(post_raid[i], direction, baseline)
        if not ok:
            continue

        candidate_fvg = _find_fvg(post_raid[i - 2:i + 1], direction, baseline)
        if candidate_fvg is None:
            continue

        # The FVG must be formed after MSS, not before it.
        if candidate_fvg.epoch <= post_raid[mss_index].epoch:
            continue

        displacement_index = i
        displacement_ratio = ratio
        fvg = candidate_fvg
        baseline_atr = baseline
        break

    if (
        displacement_index is None
        or displacement_ratio is None
        or fvg is None
        or baseline_atr is None
    ):
        return _no_signal(
            "No post-MSS displacement candle with a valid FVG",
            htf_bias=direction,
            liquidity_type=liquidity_type,
            sweep_level=sweep_level,
            mss_level=mss_level,
        )

    # 6. Find the last opposing candle before displacement.
    ob = _find_order_block(post_raid, direction, displacement_index)
    if ob is None:
        return _no_signal(
            "No candidate OB before displacement",
            htf_bias=direction,
            liquidity_type=liquidity_type,
            sweep_level=sweep_level,
            mss_level=mss_level,
            displacement_atr=displacement_ratio,
            fvg=fvg,
        )

    # 7. Require a non-empty FVG/OB overlap.
    overlap_low = max(fvg.low, ob.low)
    overlap_high = min(fvg.high, ob.high)

    if overlap_low >= overlap_high:
        return _no_signal(
            "FVG and candidate OB do not have a positive-width overlap",
            htf_bias=direction,
            liquidity_type=liquidity_type,
            sweep_level=sweep_level,
            mss_level=mss_level,
            displacement_atr=displacement_ratio,
            fvg=fvg,
            order_block=ob,
        )

    overlap = Zone(
        low=overlap_low,
        high=overlap_high,
        kind="FVG_OB_OVERLAP",
        epoch=max(fvg.epoch, ob.epoch),
    )

    # 8. A later candle must retrace into the overlap and close directionally.
    confirmation_index: Optional[int] = None
    confirmation: Optional[Candle] = None
    overlap_midpoint = overlap.midpoint

    for i in range(displacement_index + 1, len(post_raid)):
        candle = post_raid[i]

        # Reject retracements occurring too far from the overlap.
        distance = (
            overlap.low - candle.high
            if candle.high < overlap.low
            else candle.low - overlap.high
            if candle.low > overlap.high
            else 0.0
        )

        if distance > baseline_atr * MAX_RETRACE_DISTANCE_ATR:
            continue

        if not _zone_touch(candle, overlap):
            continue

        confirmed = (
            candle.close > overlap_midpoint
            if direction == "BULLISH"
            else candle.close < overlap_midpoint
        )

        if confirmed:
            confirmation_index = i
            confirmation = candle
            break

    if confirmation is None or confirmation_index is None:
        return _no_signal(
            "No post-displacement retracement and directional confirmation",
            htf_bias=direction,
            liquidity_type=liquidity_type,
            sweep_level=sweep_level,
            mss_level=mss_level,
            displacement_atr=displacement_ratio,
            fvg=fvg,
            order_block=ob,
        )

    # The caller must observe the next M1 candle before attaching entry.
    # Do not invent an entry price or use a future candle in this function.
    return SignalResult(
        signal="CALL" if direction == "BULLISH" else "PUT",
        reason="All configured SMC V3 conditions passed",
        htf_bias=direction,
        liquidity_type=liquidity_type,
        sweep_level=sweep_level,
        mss_level=mss_level,
        displacement_atr=displacement_ratio,
        fvg=fvg,
        order_block=ob,
        premium_discount=location,
        details={
            "d1_bias": d1_bias,
            "h4_bias": h4_bias,
            "dealing_range_low": range_low,
            "dealing_range_high": range_high,
            "dealing_range_midpoint": midpoint,
            "raid_epoch": raid_candle.epoch,
            "raid_close_epoch": raid_close_epoch,
            "mss_epoch": post_raid[mss_index].epoch,
            "displacement_epoch": post_raid[displacement_index].epoch,
            "confirmation_epoch": confirmation.epoch,
            "confirmation_index_in_post_raid": confirmation_index,
            "entry_rule": "next M1 candle open after confirmation",
            "warning": (
                "Candidate SMC signal only. No profitability guarantee. "
                "Validate using historical data, transaction assumptions, "
                "and the actual binary payout."
            ),
        },
    )


def attach_next_m1_entry(
    result: SignalResult,
    next_m1: Candle,
) -> SignalResult:
    """Attach the observed next M1 candle open to a confirmed signal."""
    if result.signal not in ("CALL", "PUT"):
        return result

    if not isinstance(next_m1, Candle) or not next_m1.valid():
        return _no_signal("Next M1 entry candle is invalid")

    if result.details is None:
        return _no_signal("Signal has no confirmation metadata")

    confirmation_epoch = result.details.get("confirmation_epoch")
    if not isinstance(confirmation_epoch, int):
        return _no_signal("Missing confirmation epoch")

    if next_m1.epoch < confirmation_epoch + M1_SECONDS:
        return _no_signal(
            "Entry candle must start after the confirmation candle closes"
        )

    details = dict(result.details)
    details["entry_rule"] = "observed next M1 candle open"

    return SignalResult(
        signal=result.signal,
        reason=result.reason,
        entry_epoch=next_m1.epoch,
        entry_price=next_m1.open,
        htf_bias=result.htf_bias,
        liquidity_type=result.liquidity_type,
        sweep_level=result.sweep_level,
        mss_level=result.mss_level,
        displacement_atr=result.displacement_atr,
        fvg=result.fvg,
        order_block=result.order_block,
        premium_discount=result.premium_discount,
        details=details,
    )
