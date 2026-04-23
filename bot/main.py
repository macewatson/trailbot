import json
import logging
import os
import signal
import sys
import time
from math import isnan
from pathlib import Path
from threading import Event

from dotenv import load_dotenv
from ib_insync import IB, Stock
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from bot.trailing import process_stop
from bot.vwap import VWAPCalculator
from bot.ibkr import place_exit_order

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

TRADES_FILE = ROOT / "data" / "trades.json"
SETTINGS_FILE = ROOT / "config" / "settings.json"
LOG_FILE = ROOT / "logs" / "trailbot.log"

ACTIVE_STATUSES = {"WATCHING", "TRAILING", "TIGHTENED"}
RECONNECT_DELAYS = [5, 10, 30, 60]


# ---------------------------------------------------------------------------
# Config / state I/O
# ---------------------------------------------------------------------------

def load_settings() -> dict:
    with open(SETTINGS_FILE) as f:
        return json.load(f)


def load_trades() -> dict:
    if not TRADES_FILE.exists():
        return {}
    with open(TRADES_FILE) as f:
        return json.load(f)


def save_trades(trades: dict) -> None:
    tmp = str(TRADES_FILE) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(trades, f, indent=2)
    os.replace(tmp, TRADES_FILE)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging(log_level: str) -> logging.Logger:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("trailbot")
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    fmt = logging.Formatter("%(asctime)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(LOG_FILE)
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    for name in ("ib_insync.ib", "ib_insync.client", "ib_insync.wrapper"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    return logger


def log_event(logger: logging.Logger, ticker: str, mode: str, event: str, **kwargs) -> None:
    kv = " ".join(f"{k}={v}" for k, v in kwargs.items())
    msg = f"{ticker:<6} | {mode:<8} | {event}"
    if kv:
        msg += f" | {kv}"
    logger.info(msg)


# ---------------------------------------------------------------------------
# IB Gateway connection
# ---------------------------------------------------------------------------

def connect_ib(settings: dict, logger: logging.Logger) -> IB:
    host = settings["ibkr"]["host"]
    port = settings["ibkr"]["port"]
    client_id = settings["ibkr"]["client_id"]
    delays = RECONNECT_DELAYS[:]
    attempt = 0
    while True:
        delay = delays[min(attempt, len(delays) - 1)]
        try:
            ib = IB()
            ib.connect(host, port, clientId=client_id)
            logger.info(f"BOT      | connected     | {host}:{port} clientId={client_id}")
            return ib
        except Exception as e:
            logger.error(f"BOT      | connect failed | {e} — retry in {delay}s")
            time.sleep(delay)
            attempt += 1


# ---------------------------------------------------------------------------
# Market data helpers
# ---------------------------------------------------------------------------

def make_contract(trade: dict) -> Stock:
    return Stock(trade["ticker"], trade["exchange"], trade["currency"])


def get_bid(ticker_obj) -> float | None:
    try:
        bid = ticker_obj.bid
        if bid is None or (isinstance(bid, float) and isnan(bid)) or bid <= 0:
            return None
        return bid
    except Exception:
        return None


def subscribe(ib: IB, trades: dict) -> dict:
    subs = {}
    for ticker, trade in trades.items():
        if trade["status"] in ACTIVE_STATUSES:
            t = ib.reqMktData(make_contract(trade), "", False, False)
            subs[ticker] = t
    return subs


# ---------------------------------------------------------------------------
# Watchdog — hot-reload trades.json when CLI writes it
# ---------------------------------------------------------------------------

class TradesWatcher(FileSystemEventHandler):
    def __init__(self):
        self._dirty = Event()

    def _mark(self, path: str) -> None:
        if Path(path).name == "trades.json":
            self._dirty.set()

    def on_modified(self, event):
        self._mark(event.src_path)

    def on_created(self, event):
        self._mark(event.src_path)

    def on_moved(self, event):
        # os.replace() on Linux uses rename() → watchdog fires FileMovedEvent
        self._mark(event.dest_path)

    def consume(self) -> bool:
        if self._dirty.is_set():
            self._dirty.clear()
            return True
        return False


# ---------------------------------------------------------------------------
# Main poll loop
# ---------------------------------------------------------------------------

def run_loop(ib: IB, settings: dict, logger: logging.Logger) -> None:
    poll_interval = settings["bot"]["poll_interval_seconds"]
    trades = load_trades()
    subs = subscribe(ib, trades)
    vwap_calc = VWAPCalculator(ib)

    watcher = TradesWatcher()
    observer = Observer()
    observer.schedule(watcher, str(TRADES_FILE.parent), recursive=False)
    observer.start()

    active_count = sum(1 for t in trades.values() if t["status"] in ACTIVE_STATUSES)
    logger.info(f"BOT      | loop started  | watching {active_count} active trade(s)")

    try:
        while True:
            ib.sleep(poll_interval)

            # Hot-reload on CLI changes
            if watcher.consume():
                new_trades = load_trades()
                for ticker, trade in new_trades.items():
                    if ticker not in subs and trade["status"] in ACTIVE_STATUSES:
                        subs[ticker] = ib.reqMktData(make_contract(trade), "", False, False)
                        log_event(logger, ticker, trade["stop_mode"], "added_to_watchlist")
                for ticker in list(subs):
                    if ticker not in new_trades:
                        ib.cancelMktData(subs.pop(ticker).contract)
                        log_event(logger, ticker, "—", "removed_from_watchlist")
                trades = new_trades

            changed = False

            for ticker, trade in list(trades.items()):
                if trade["status"] not in ACTIVE_STATUSES:
                    continue

                ticker_obj = subs.get(ticker)
                if ticker_obj is None:
                    continue

                price = get_bid(ticker_obj)
                if price is None:
                    continue

                prev_stop = trade["current_stop"]
                vwap = vwap_calc.get_vwap(ticker, trade["exchange"], trade["currency"]) \
                       if trade.get("vwap_aware") else None

                updated = process_stop(trade, price, vwap=vwap)

                # Log stop movements
                if updated["current_stop"] != prev_stop:
                    log_event(logger, ticker, updated["stop_mode"], "stop_moved",
                              old=f"{prev_stop:.2f}",
                              new=f"{updated['current_stop']:.2f}",
                              hwm=f"{updated['high_water_mark']:.2f}",
                              price=f"{price:.2f}")

                # Log mode transitions
                if updated["stop_mode"] != trade["stop_mode"]:
                    log_event(logger, ticker, updated["stop_mode"], "mode_change",
                              from_mode=trade["stop_mode"],
                              price=f"{price:.2f}")

                # Handle exit
                if updated.get("exit_triggered"):
                    log_event(logger, ticker, updated["stop_mode"], "EXIT",
                              stop=f"{updated['current_stop']:.2f}",
                              price=f"{price:.2f}")
                    try:
                        place_exit_order(ib, updated)
                    except Exception as e:
                        logger.error(f"{ticker:<6} | order failed  | {e}")
                        updated["status"] = "EXITED"

                    if ticker in subs:
                        ib.cancelMktData(subs.pop(ticker).contract)
                    vwap_calc.invalidate(ticker)

                trades[ticker] = updated
                changed = True

            if changed:
                save_trades(trades)

    finally:
        observer.stop()
        observer.join()


# ---------------------------------------------------------------------------
# Entry point with outer reconnect loop
# ---------------------------------------------------------------------------

def main() -> None:
    settings = load_settings()

    assert not settings["bot"]["use_native_stop_orders"], (
        "use_native_stop_orders must be false — bot manages its own monitoring loop"
    )

    logger = setup_logging(settings["bot"]["log_level"])
    logger.info("BOT      | TrailBot starting")

    def handle_signal(sig, _frame):
        logger.info("BOT      | shutdown signal received — exiting")
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    while True:
        ib = connect_ib(settings, logger)
        try:
            run_loop(ib, settings, logger)
        except Exception as e:
            logger.error(f"BOT      | run loop error  | {e}", exc_info=True)
        finally:
            try:
                ib.disconnect()
            except Exception:
                pass
        logger.warning("BOT      | disconnected — reconnecting...")


if __name__ == "__main__":
    main()
