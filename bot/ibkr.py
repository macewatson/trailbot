import logging
import os
from math import isnan

from ib_insync import LimitOrder, Stock

logger = logging.getLogger("trailbot")

ACCOUNT_ENV = {
    "individual": "IBKR_ACCOUNT_INDIVIDUAL",
    "roth": "IBKR_ACCOUNT_ROTH",
}


def _resolve_account(ib, label: str) -> str:
    """Return the account ID to use for the order.

    When connected to paper gateway the managed account is a DU-prefixed paper
    account, not the live U-prefixed ID stored in .env.  If the configured ID
    isn't in the managed accounts list, fall back to the first managed account.
    """
    configured = os.getenv(ACCOUNT_ENV.get(label.lower(), ""), "")
    managed = ib.managedAccounts()
    if configured in managed:
        return configured
    return managed[0] if managed else configured


def place_exit_order(ib, trade: dict) -> None:
    ticker = trade["ticker"]
    mode = trade["stop_mode"]
    account_id = _resolve_account(ib, trade["account"])

    contract = Stock(ticker, trade["exchange"], trade["currency"])

    # Snapshot bid price
    t = ib.reqTickers(contract)
    bid = t[0].bid if t else None
    if bid is None or (isinstance(bid, float) and isnan(bid)) or bid <= 0:
        last = t[0].last if t else None
        if last and not (isinstance(last, float) and isnan(last)) and last > 0:
            bid = last
        else:
            logger.error(f"{ticker:<6} | no price data — exit order NOT placed")
            return

    lmt_price = round(bid - 0.05, 2)
    qty = trade["quantity"]

    order = LimitOrder("SELL", qty, lmt_price)
    order.account = account_id
    order.tif = "DAY"

    trade_obj = ib.placeOrder(contract, order)
    order_id = trade_obj.order.orderId

    logger.info(
        f"{ticker:<6} | {mode:<8} | order_placed | "
        f"id={order_id} qty={qty} lmt={lmt_price} acct={account_id}"
    )

    # Wait up to 30s for fill (paper fills are fast; live may be slower)
    for _ in range(15):
        ib.sleep(2)
        status = trade_obj.orderStatus.status
        if status in ("Filled", "Cancelled", "Inactive"):
            break

    status = trade_obj.orderStatus.status
    if status == "Filled":
        fill_price = round(trade_obj.orderStatus.avgFillPrice, 4)
        logger.info(
            f"{ticker:<6} | {mode:<8} | FILLED        | "
            f"qty={qty} fill_price={fill_price} order_id={order_id}"
        )
        trade["status"] = "EXITED"
        trade["fill_price"] = fill_price
    else:
        logger.warning(
            f"{ticker:<6} | {mode:<8} | fill_timeout   | "
            f"status={status} order_id={order_id} — marking EXITED anyway"
        )
        trade["status"] = "EXITED"
