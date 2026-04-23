import time
from datetime import datetime

import pytz

ET = pytz.timezone("America/New_York")
CACHE_TTL = 60  # seconds


class VWAPCalculator:
    def __init__(self, cp):
        self._cp = cp
        self._cache: dict[str, float] = {}
        self._cache_ts: dict[str, float] = {}

    def get_vwap(self, ticker: str) -> float | None:
        now = time.monotonic()
        if ticker in self._cache and now - self._cache_ts.get(ticker, 0) < CACHE_TTL:
            return self._cache[ticker]

        conid = self._cp._conid_cache.get(ticker)
        if not conid:
            return None

        bars = self._cp.get_historical_bars(conid, period="1d", bar="5min")
        if not bars:
            return None

        # Filter to bars since 09:30 ET today; fall back to all bars pre-market
        now_et = datetime.now(ET)
        session_open_ms = int(
            now_et.replace(hour=9, minute=30, second=0, microsecond=0).timestamp() * 1000
        )
        today_bars = [b for b in bars if b.get("t", 0) >= session_open_ms]
        if not today_bars:
            today_bars = bars  # pre-market: use all returned bars

        total_pv = 0.0
        total_v = 0.0
        for b in today_bars:
            v = b.get("v", 0)
            if v <= 0:
                continue
            tp = (b.get("h", 0) + b.get("l", 0) + b.get("c", 0)) / 3  # typical price
            if tp <= 0:
                continue
            total_pv += tp * v
            total_v += v

        if total_v == 0:
            return None

        vwap = round(total_pv / total_v, 4)
        self._cache[ticker] = vwap
        self._cache_ts[ticker] = now
        return vwap

    def invalidate(self, ticker: str) -> None:
        self._cache.pop(ticker, None)
        self._cache_ts.pop(ticker, None)
