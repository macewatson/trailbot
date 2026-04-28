import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import click
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

TRADES_FILE = ROOT / "data" / "trades.json"
SETTINGS_FILE = ROOT / "config" / "settings.json"
LOG_FILE = ROOT / "logs" / "trailbot.log"

ACCOUNT_ENV = {
    "individual": "IBKR_ACCOUNT_INDIVIDUAL",
    "roth": "IBKR_ACCOUNT_ROTH",
}


def get_account_id(label: str) -> str:
    key = ACCOUNT_ENV.get(label.lower())
    if not key:
        raise click.BadParameter(f"Unknown account '{label}'. Use: individual, roth")
    value = os.getenv(key)
    if not value:
        raise click.BadParameter(f"{key} is not set in .env")
    return value


def load_trades() -> dict:
    if not TRADES_FILE.exists():
        return {}
    with open(TRADES_FILE) as f:
        return json.load(f)


def save_trades(trades: dict) -> None:
    TRADES_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(TRADES_FILE) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(trades, f, indent=2)
    os.replace(tmp, TRADES_FILE)


def load_settings() -> dict:
    with open(SETTINGS_FILE) as f:
        return json.load(f)


def connect_ib():
    from ib_insync import IB, util
    for name in ("ib_insync.ib", "ib_insync.client", "ib_insync.wrapper"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    cfg = load_settings()["ibkr"]
    ib = IB()
    ib.connect(cfg["host"], cfg["port"], clientId=cfg["cli_client_id"])
    return ib


@click.group()
def cli():
    pass


@cli.command()
@click.argument("ticker")
@click.argument("entry_price", type=float)
@click.option("--account", required=True,
              type=click.Choice(["individual", "roth"], case_sensitive=False),
              help="Account: individual or roth")
@click.option("--qty", required=True, type=int, help="Number of shares")
@click.option("--stop", "hard_stop", required=True, type=float, help="Hard stop price")
@click.option("--trigger", "trail_trigger", default=None, type=float,
              help="Price to activate trailing stop")
@click.option("--trail", "trail_amount", default=None, type=float,
              help="Trail distance in dollars")
@click.option("--trail-pct", "trail_pct", default=None, type=float,
              help="Trail distance as %% of entry price (e.g. 0.75 = 0.75%%)")
@click.option("--tighten", "tighten_at", default=None, type=float,
              help="Price to switch to tight trail")
@click.option("--tight-trail", "tight_trail_amount", default=None, type=float,
              help="Tight trail distance in dollars")
@click.option("--tight-trail-pct", "tight_trail_pct", default=None, type=float,
              help="Tight trail distance as %% of entry price")
@click.option("--vwap", "vwap_aware", is_flag=True, default=False,
              help="Enable VWAP-aware trail adjustment")
def addtrade(ticker, entry_price, account, qty, hard_stop,
             trail_trigger, trail_amount, trail_pct, tighten_at,
             tight_trail_amount, tight_trail_pct, vwap_aware):
    """Add a trade to the watchlist."""
    ticker = ticker.upper()
    account = account.lower()
    get_account_id(account)  # validate early before connecting

    if trail_amount is not None and trail_pct is not None:
        raise click.UsageError("--trail and --trail-pct are mutually exclusive.")
    if tight_trail_amount is not None and tight_trail_pct is not None:
        raise click.UsageError("--tight-trail and --tight-trail-pct are mutually exclusive.")

    try:
        ib = connect_ib()
        from ib_insync import Stock
        contract = Stock(ticker, "SMART", "USD")
        details = ib.reqContractDetails(contract)
        ib.disconnect()
    except Exception as e:
        click.echo(f"Error: could not validate ticker — {e}", err=True)
        sys.exit(1)

    if not details:
        click.echo(f"Error: {ticker} not found on IBKR SMART.", err=True)
        sys.exit(1)

    trades = load_trades()
    if ticker in trades and trades[ticker]["status"] != "EXITED":
        click.echo(f"Error: {ticker} is already in watchlist (status={trades[ticker]['status']}). "
                   "Use updatetrade or removetrade first.", err=True)
        sys.exit(1)

    defaults = load_settings().get("defaults", {})

    if trail_pct is not None:
        trail_amount = round(entry_price * trail_pct / 100, 2)
    elif trail_amount is None:
        trail_amount = defaults.get("trail_amount", 1.50)
        trail_pct = None

    if tight_trail_pct is not None:
        tight_trail_amount = round(entry_price * tight_trail_pct / 100, 2)
    elif tight_trail_amount is None:
        tight_trail_amount = defaults.get("tight_trail_amount", 0.75)
        tight_trail_pct = None

    trade = {
        "ticker": ticker,
        "account": account,
        "exchange": "SMART",
        "currency": "USD",
        "asset_type": "STK",
        "entry_price": entry_price,
        "quantity": qty,
        "direction": "LONG",
        "hard_stop": hard_stop,
        "trail_trigger": trail_trigger,
        "trail_amount": trail_amount,
        "trail_pct": trail_pct,
        "tighten_at": tighten_at,
        "tight_trail_amount": tight_trail_amount,
        "tight_trail_pct": tight_trail_pct,
        "vwap_aware": vwap_aware,
        "status": "WATCHING",
        "current_stop": hard_stop,
        "stop_mode": "HARD",
        "high_water_mark": entry_price,
        "added_at": datetime.now().isoformat(timespec="seconds"),
        "notes": "",
    }

    trades[ticker] = trade
    save_trades(trades)

    parts = [f"entry={entry_price}", f"stop={hard_stop}", f"account={account}"]
    if trail_trigger:
        parts.append(f"trigger={trail_trigger}")
    if trail_pct is not None:
        parts.append(f"trail={trail_amount} ({trail_pct}%)")
    else:
        parts.append(f"trail={trail_amount}")
    click.echo(f"Added {ticker}  {' | '.join(parts)}")


@cli.command()
@click.option("--account", default=None,
              type=click.Choice(["individual", "roth"], case_sensitive=False),
              help="Filter by account")
def listtrades(account):
    """List all active trades."""
    trades = load_trades()
    rows = [t for t in trades.values() if t["status"] != "EXITED"]
    if account:
        rows = [t for t in rows if t["account"] == account.lower()]

    if not rows:
        click.echo("No active trades.")
        return

    header = f"{'TICKER':<8}  {'ACCOUNT':<12}  {'STATUS':<10}  {'MODE':<9}  " \
             f"{'ENTRY':>7}  {'STOP':>7}  {'HWM':>7}  {'VWAP'}"
    click.echo(header)
    click.echo("-" * len(header))
    for t in sorted(rows, key=lambda x: x["ticker"]):
        click.echo(
            f"{t['ticker']:<8}  {t['account']:<12}  {t['status']:<10}  {t['stop_mode']:<9}  "
            f"{t['entry_price']:>7.2f}  {t['current_stop']:>7.2f}  {t['high_water_mark']:>7.2f}  "
            f"{'yes' if t.get('vwap_aware') else 'no'}"
        )


@cli.command()
@click.argument("ticker")
@click.option("--stop", "hard_stop", default=None, type=float, help="New hard stop price")
@click.option("--trigger", "trail_trigger", default=None, type=float)
@click.option("--trail", "trail_amount", default=None, type=float)
@click.option("--trail-pct", "trail_pct", default=None, type=float,
              help="Trail distance as %% of entry price")
@click.option("--tighten", "tighten_at", default=None, type=float)
@click.option("--tight-trail", "tight_trail_amount", default=None, type=float)
@click.option("--tight-trail-pct", "tight_trail_pct", default=None, type=float,
              help="Tight trail distance as %% of entry price")
def updatetrade(ticker, hard_stop, trail_trigger, trail_amount, trail_pct,
                tighten_at, tight_trail_amount, tight_trail_pct):
    """Update parameters for an existing trade."""
    ticker = ticker.upper()

    if trail_amount is not None and trail_pct is not None:
        raise click.UsageError("--trail and --trail-pct are mutually exclusive.")
    if tight_trail_amount is not None and tight_trail_pct is not None:
        raise click.UsageError("--tight-trail and --tight-trail-pct are mutually exclusive.")

    trades = load_trades()
    if ticker not in trades:
        click.echo(f"Error: {ticker} not in watchlist.", err=True)
        sys.exit(1)

    trade = trades[ticker]
    updated = []

    if hard_stop is not None:
        if trade["direction"] == "LONG":
            effective = max(hard_stop, trade["current_stop"])
            if effective != hard_stop:
                click.echo(f"Note: stop raised to {effective} (cannot decrease below current {trade['current_stop']})")
            trade["hard_stop"] = effective
            trade["current_stop"] = effective
            updated.append(f"stop={effective}")
        else:
            trade["hard_stop"] = hard_stop
            trade["current_stop"] = hard_stop
            updated.append(f"stop={hard_stop}")

    if trail_trigger is not None:
        trade["trail_trigger"] = trail_trigger
        updated.append(f"trigger={trail_trigger}")

    if trail_pct is not None:
        computed = round(trade["entry_price"] * trail_pct / 100, 2)
        trade["trail_amount"] = computed
        trade["trail_pct"] = trail_pct
        updated.append(f"trail={computed} ({trail_pct}%)")
    elif trail_amount is not None:
        trade["trail_amount"] = trail_amount
        trade["trail_pct"] = None
        updated.append(f"trail={trail_amount}")

    if tighten_at is not None:
        trade["tighten_at"] = tighten_at
        updated.append(f"tighten_at={tighten_at}")

    if tight_trail_pct is not None:
        computed = round(trade["entry_price"] * tight_trail_pct / 100, 2)
        trade["tight_trail_amount"] = computed
        trade["tight_trail_pct"] = tight_trail_pct
        updated.append(f"tight_trail={computed} ({tight_trail_pct}%)")
    elif tight_trail_amount is not None:
        trade["tight_trail_amount"] = tight_trail_amount
        trade["tight_trail_pct"] = None
        updated.append(f"tight_trail={tight_trail_amount}")

    if not updated:
        click.echo("Nothing to update.")
        return

    trades[ticker] = trade
    save_trades(trades)
    click.echo(f"Updated {ticker}: {', '.join(updated)}")


@cli.command()
@click.argument("ticker")
def pausetrade(ticker):
    """Pause monitoring for a trade."""
    ticker = ticker.upper()
    trades = load_trades()
    if ticker not in trades:
        click.echo(f"Error: {ticker} not in watchlist.", err=True)
        sys.exit(1)
    trades[ticker]["status"] = "PAUSED"
    save_trades(trades)
    click.echo(f"{ticker} paused.")


@cli.command()
@click.argument("ticker")
def resumetrade(ticker):
    """Resume a paused trade."""
    ticker = ticker.upper()
    trades = load_trades()
    if ticker not in trades:
        click.echo(f"Error: {ticker} not in watchlist.", err=True)
        sys.exit(1)
    trades[ticker]["status"] = "WATCHING"
    save_trades(trades)
    click.echo(f"{ticker} resumed.")


@cli.command()
@click.argument("ticker")
def removetrade(ticker):
    """Remove a trade from the watchlist."""
    ticker = ticker.upper()
    trades = load_trades()
    if ticker not in trades:
        click.echo(f"Error: {ticker} not in watchlist.", err=True)
        sys.exit(1)
    if not click.confirm(f"Remove {ticker} from watchlist?", default=False):
        click.echo("Cancelled.")
        return
    del trades[ticker]
    save_trades(trades)
    click.echo(f"{ticker} removed.")


@cli.command()
@click.argument("ticker", required=False)
def tradelog(ticker):
    """Show recent log entries, optionally filtered by ticker."""
    if not LOG_FILE.exists():
        click.echo("No log file found.")
        return
    with open(LOG_FILE) as f:
        lines = f.readlines()
    if ticker:
        ticker = ticker.upper()
        lines = [l for l in lines if f"| {ticker} |" in l]
    for line in lines[-200:]:
        click.echo(line, nl=False)


def _fmt_trail(amount, pct):
    if pct is not None:
        return f"${amount:.2f} ({pct}%)"
    if amount is not None:
        return f"${amount:.2f}"
    return "—"


@cli.command()
def botstatus():
    """Show watchlist summary with trail configuration."""
    trades = load_trades()
    if not trades:
        click.echo("Watchlist is empty.")
        return

    by_status = {}
    for t in trades.values():
        by_status.setdefault(t["status"], 0)
        by_status[t["status"]] += 1
    summary = " | ".join(f"{s.lower()}={n}" for s, n in sorted(by_status.items()))
    click.echo(f"{len(trades)} trade(s): {summary}\n")

    header = f"{'TICKER':<8}  {'STATUS':<10}  {'MODE':<8}  {'TRAIL':<18}  {'TIGHT TRAIL':<18}  VWAP"
    click.echo(header)
    click.echo("-" * len(header))
    for t in sorted(trades.values(), key=lambda x: x["ticker"]):
        trail_str = _fmt_trail(t.get("trail_amount"), t.get("trail_pct"))
        tight_str = _fmt_trail(t.get("tight_trail_amount"), t.get("tight_trail_pct"))
        click.echo(
            f"{t['ticker']:<8}  {t['status']:<10}  {t['stop_mode']:<8}  "
            f"{trail_str:<18}  {tight_str:<18}  {'yes' if t.get('vwap_aware') else 'no'}"
        )


@cli.command()
def checkconn():
    """Test IB Gateway connection."""
    try:
        ib = connect_ib()
        accounts = ib.managedAccounts()
        server_time = ib.reqCurrentTime()
        ib.disconnect()
        click.echo(f"Connected  accounts={','.join(accounts)}  server_time={server_time}")
    except Exception as e:
        click.echo(f"Connection failed: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    cli()
