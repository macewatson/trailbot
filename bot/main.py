import json
import logging
import os
import signal
import sys
import time
from pathlib import Path
from threading import Event, Thread

from dotenv import load_dotenv
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from bot.trailing import process_stop
from bot.vwap import VWAPCalculator
from bot.ibkr import CpApi, place_exit_order

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
    return logger


def log_event(logger: logging.Logger, ticker: str, mode: str, event: str, **kwargs) -> None:
    kv = " ".join(f"{k}={v}" for k, v in kwargs.items())
    msg = f"{ticker:<6} | {mode:<8} | {event}"
    if kv:
        msg += f" | {kv}"
    logger.info(msg)


# ---------------------------------------------------------------------------
# CPAPI connection
# ---------------------------------------------------------------------------

def connect_cpapi(settings: dict, logger: logging.Logger) -> CpApi:
    """Wait until the Client Portal Gateway is reachable and authenticated."""
    host = settings["cpapi"]["host"]
    port = settings["cpapi"]["port"]
    delays = RECONNECT_DELAYS[:]
    attempt = 0
    while True:
        delay = delays[min(attempt, len(delays) - 1)]
        try:
            cp = CpApi(host, port)
            if cp.is_authenticated():
                logger.info(f"BOT      | connected     | cpapi {host}:{port}")
                return cp
            logger.warning(
                f"BOT      | not authenticated | open https://{host}:{port} to log in "
                f"— retry in {delay}s"
            )
        except Exception as e:
            logger.error(f"BOT      | connect failed | {e} — retry in {delay}s")
        time.sleep(delay)
        attempt += 1


# ---------------------------------------------------------------------------
# conid resolution
# ---------------------------------------------------------------------------

def resolve_conids(cp: CpApi, trades: dict, logger: logging.Logger) -> bool:
    """Resolve missing conids for active trades. Returns True if any changed."""
    changed = False
    for ticker, trade in trades.items():
        if trade["status"] not in ACTIVE_STATUSES:
            continue
        existing = trade.get("conid")
        if existing:
            cp._conid_cache[ticker] = existing  # warm the in-process cache
            continue
        conid = cp.resolve_conid(ticker)
        if conid:
            trade["conid"] = conid
            changed = True
            logger.info(f"{ticker:<6} | conid resolved | {conid}")
        else:
            logger.warning(f"{ticker:<6} | conid NOT resolved — skipping pricing")
    return changed


# ---------------------------------------------------------------------------
# Session keepalive (background thread)
# ---------------------------------------------------------------------------

def keepalive_worker(cp: CpApi, stop_event: Event) -> None:
    while not stop_event.wait(60):
        cp.tickle()


# ---------------------------------------------------------------------------
# Watchdog — hot-reload trades.json when CLI writes it
# ---------------------------------------------------------------------------

class TradesWatcher(FileSystemEventHandler):
    def __init__(self):
        self._dirty = Event()

    def _mark(self, path: str) -> None:
        if Path(path).name == "trades.json":
            self._dirty.set()

    def on_modified(self, event): self._mark(event.src_path)
    def on_created(self, event): self._mark(event.src_path)
    def on_moved(self, event): self._mark(event.dest_path)

    def consume(self) -> bool:
        if self._dirty.is_set():
            self._dirty.clear()
            return True
        return False


# ---------------------------------------------------------------------------
# Main poll loop
# ---------------------------------------------------------------------------

def run_loop(cp: CpApi, settings: dict, logger: logging.Logger) -> None:
    poll_interval = settings["bot"]["poll_interval_seconds"]
    trades = load_trades()
    if resolve_conids(cp, trades, logger):
        save_trades(trades)  # persist newly-resolved conids

    vwap_calc = VWAPCalculator(cp)

    stop_event = Event()
    keepalive_thread = Thread(target=keepalive_worker, args=(cp, stop_event), daemon=True)
    keepalive_thread.start()

    watcher = TradesWatcher()
    observer = Observer()
    observer.schedule(watcher, str(TRADES_FILE.parent), recursive=False)
    observer.start()

    active_count = sum(1 for t in trades.values() if t["status"] in ACTIVE_STATUSES)
    logger.info(f"BOT      | loop started  | watching {active_count} active trade(s)")

    try:
        while True:
            time.sleep(poll_interval)

            # Hot-reload on CLI changes
            if watcher.consume():
                new_trades = load_trades()
                if resolve_conids(cp, new_trades, logger):
                    save_trades(new_trades)
                for ticker in new_trades:
                    if ticker not in trades:
                        log_event(logger, ticker, new_trades[ticker]["stop_mode"], "added_to_watchlist")
                for ticker in list(trades):
                    if ticker not in new_trades:
                        log_event(logger, ticker, "—", "removed_from_watchlist")
                        vwap_calc.invalidate(ticker)
                trades = new_trades

            changed = False

            for ticker, trade in list(trades.items()):
                if trade["status"] not in ACTIVE_STATUSES:
                    continue

                conid = trade.get("conid")
                if not conid:
                    continue

                price = cp.get_price(conid)
                if price is None:
                    continue

                prev_stop = trade["current_stop"]
                vwap = (
                    vwap_calc.get_vwap(ticker)
                    if trade.get("vwap_aware")
                    else None
                )

                updated = process_stop(trade, price, vwap=vwap)

                if updated["current_stop"] != prev_stop:
                    log_event(
                        logger, ticker, updated["stop_mode"], "stop_moved",
                        old=f"{prev_stop:.2f}",
                        new=f"{updated['current_stop']:.2f}",
                        hwm=f"{updated['high_water_mark']:.2f}",
                        price=f"{price:.2f}",
                    )

                if updated["stop_mode"] != trade["stop_mode"]:
                    log_event(
                        logger, ticker, updated["stop_mode"], "mode_change",
                        from_mode=trade["stop_mode"],
                        price=f"{price:.2f}",
                    )

                if updated.get("exit_triggered"):
                    log_event(
                        logger, ticker, updated["stop_mode"], "EXIT",
                        stop=f"{updated['current_stop']:.2f}",
                        price=f"{price:.2f}",
                    )
                    try:
                        place_exit_order(cp, updated)
                    except Exception as e:
                        logger.error(f"{ticker:<6} | order failed  | {e}")
                        updated["status"] = "EXITED"

                    vwap_calc.invalidate(ticker)

                trades[ticker] = updated
                changed = True

            if changed:
                save_trades(trades)

    finally:
        stop_event.set()
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
        cp = connect_cpapi(settings, logger)
        try:
            run_loop(cp, settings, logger)
        except Exception as e:
            logger.error(f"BOT      | run loop error  | {e}", exc_info=True)
        logger.warning("BOT      | session lost — reconnecting...")


if __name__ == "__main__":
    main()
