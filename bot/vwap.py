import time
from datetime import datetime, timedelta

import pytz
from ib_insync import Stock

ET = pytz.timezone("America/New_York")
CACHE_TTL = 60  # seconds


class VWAPCalculator:
    def __init__(self, ib):
        self._ib = ib
        self._cache: dict[str, float] = {}
        self._cache_ts: dict[str, float] = {}

    def get_vwap(self, ticker: str, exchange: str = "SMART", currency: str = "USD") -> float | None:
        now = time.monotonic()
        if ticker in self._cache and now - self._cache_ts.get(ticker, 0) < CACHE_TTL:
            return self._cache[ticker]

        contract = Stock(ticker, exchange, currency)
        now_et = datetime.now(ET)
        market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)

        if now_et < market_open:
            # Pre-market — use prior trading day's session
            prior = now_et - timedelta(days=1)
            while prior.weekday() >= 5:  # skip weekends
                prior -= timedelta(days=1)
            duration = "2 D"
        else:
            duration = "1 D"

        try:
            bars = self._ib.reqHistoricalData(
                contract,
                endDateTime="",
                durationStr=duration,
                barSizeSetting="5 mins",
                whatToShow="TRADES",
                useRTH=True,
                formatDate=1,
                keepUpToDate=False,
            )
        except Exception:
            return None

        if not bars:
            return None

        # VWAP = sum(bar_vwap * volume) / sum(volume)
        # bar.average is the IBKR bar VWAP
        total_pv = sum(b.average * b.volume for b in bars if b.volume > 0)
        total_v = sum(b.volume for b in bars if b.volume > 0)

        if total_v == 0:
            return None

        vwap = round(total_pv / total_v, 4)
        self._cache[ticker] = vwap
        self._cache_ts[ticker] = now
        return vwap

    def invalidate(self, ticker: str) -> None:
        self._cache.pop(ticker, None)
        self._cache_ts.pop(ticker, None)
