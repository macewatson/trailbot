import logging
import os
import time

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger("trailbot")

ACCOUNT_ENV = {
    "individual": "IBKR_ACCOUNT_INDIVIDUAL",
    "roth": "IBKR_ACCOUNT_ROTH",
}


class CpApi:
    """Thin REST wrapper around the IBKR Client Portal Gateway."""

    def __init__(self, host: str = "127.0.0.1", port: int = 5000):
        self._base = f"https://{host}:{port}/v1/api"
        self._session = requests.Session()
        self._session.verify = False
        self._conid_cache: dict[str, int] = {}

    # --- low-level HTTP ---------------------------------------------------

    def _get(self, path: str, **kwargs):
        r = self._session.get(f"{self._base}{path}", **kwargs)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, **kwargs):
        r = self._session.post(f"{self._base}{path}", **kwargs)
        r.raise_for_status()
        return r.json()

    # --- session ----------------------------------------------------------

    def tickle(self) -> None:
        try:
            self._post("/tickle")
        except Exception as e:
            logger.warning(f"CPAPI    | tickle failed   | {e}")

    def auth_status(self) -> dict:
        return self._get("/iserver/auth/status")

    def is_authenticated(self) -> bool:
        try:
            status = self.auth_status()
            return bool(status.get("authenticated") or status.get("connected"))
        except Exception:
            return False

    # --- accounts ---------------------------------------------------------

    def get_accounts(self) -> list[str]:
        try:
            self._get("/iserver/accounts")   # preflight
            time.sleep(0.3)
            data = self._get("/iserver/accounts")
            accounts = data.get("accounts", data) if isinstance(data, dict) else data
            return [a if isinstance(a, str) else a.get("accountId", "") for a in accounts]
        except Exception as e:
            logger.warning(f"CPAPI    | get_accounts failed | {e}")
            return []

    # --- contract lookup --------------------------------------------------

    def resolve_conid(self, ticker: str) -> int | None:
        if ticker in self._conid_cache:
            return self._conid_cache[ticker]
        try:
            results = self._post(
                "/iserver/secdef/search",
                json={"symbol": ticker, "name": False, "secType": "STK"},
            )
            if not results:
                return None
            for r in results:
                if r.get("assetClass") == "STK":
                    conid = r.get("conid")
                    if conid:
                        self._conid_cache[ticker] = int(conid)
                        return int(conid)
            return None
        except Exception as e:
            logger.warning(f"CPAPI    | resolve_conid({ticker}) failed | {e}")
            return None

    # --- market data ------------------------------------------------------

    def get_snapshot(self, conid: int) -> dict:
        """Snapshot quote. Fields: 84=bid, 31=last, 86=ask.

        First call for a new conid initiates a subscription and returns no data.
        Second call (after brief delay) returns live quotes.
        """
        params = {"conids": str(conid), "fields": "84,31,86"}
        try:
            self._session.get(
                f"{self._base}/iserver/marketdata/snapshot", params=params, verify=False
            )
            time.sleep(0.2)
            r = self._session.get(
                f"{self._base}/iserver/marketdata/snapshot", params=params, verify=False
            )
            data = r.json()
            if data and isinstance(data, list):
                return data[0]
        except Exception:
            pass
        return {}

    def get_price(self, conid: int) -> float | None:
        snap = self.get_snapshot(conid)
        for field in ("84", "31"):  # bid preferred, then last
            raw = snap.get(field)
            if raw is None:
                continue
            try:
                val = float(str(raw).replace(",", ""))
                if val > 0:
                    return val
            except (ValueError, TypeError):
                pass
        return None

    def get_historical_bars(self, conid: int, period: str = "1d", bar: str = "5min") -> list[dict]:
        try:
            params = {"conid": conid, "period": period, "bar": bar, "outsideRth": "0"}
            data = self._get("/iserver/marketdata/history", params=params)
            return data.get("data", [])
        except Exception:
            return []

    # --- orders -----------------------------------------------------------

    def place_limit_sell(self, account_id: str, conid: int, qty: int, price: float) -> str | None:
        """Place a DAY limit sell order. Returns order_id string or None."""
        body = {
            "orders": [
                {
                    "conid": conid,
                    "orderType": "LMT",
                    "side": "SELL",
                    "quantity": qty,
                    "price": price,
                    "tif": "DAY",
                    "cOID": f"TB_{conid}_{int(time.time())}",
                }
            ]
        }
        try:
            result = self._post(f"/iserver/account/{account_id}/orders", json=body)
        except Exception as e:
            logger.error(f"CPAPI    | place_order failed | {e}")
            return None

        # CPAPI may return a confirmation question before the actual order reply.
        if isinstance(result, list):
            for item in result:
                if "id" in item and "message" in item:
                    # Auto-confirm the warning
                    reply_id = item["id"]
                    try:
                        confirm = self._post(
                            f"/iserver/reply/{reply_id}", json={"confirmed": True}
                        )
                        if isinstance(confirm, list) and confirm:
                            return str(confirm[0].get("order_id", ""))
                    except Exception as e:
                        logger.error(f"CPAPI    | order confirm failed | {e}")
                        return None
                if "order_id" in item:
                    return str(item["order_id"])

        if isinstance(result, dict) and "order_id" in result:
            return str(result["order_id"])

        return None

    def get_order_status(self, account_id: str, order_id: str) -> str:
        """Return IBKR order status string, or 'Unknown' on any error."""
        try:
            data = self._get(f"/iserver/account/{account_id}/orders")
            orders = data.get("orders", []) if isinstance(data, dict) else []
            for o in orders:
                if str(o.get("orderId")) == str(order_id):
                    return o.get("status", "Unknown")
        except Exception:
            pass
        return "Unknown"


# ---------------------------------------------------------------------------
# Public helpers used by main.py and cli
# ---------------------------------------------------------------------------

def resolve_account(cp: CpApi, label: str) -> str:
    configured = os.getenv(ACCOUNT_ENV.get(label.lower(), ""), "")
    managed = cp.get_accounts()
    if configured in managed:
        return configured
    return managed[0] if managed else configured


def place_exit_order(cp: CpApi, trade: dict) -> None:
    ticker = trade["ticker"]
    mode = trade["stop_mode"]
    conid = trade.get("conid")

    if not conid:
        logger.error(f"{ticker:<6} | {mode:<8} | no conid — exit NOT placed")
        return

    account_id = resolve_account(cp, trade["account"])
    price = cp.get_price(conid)

    if price is None or price <= 0:
        logger.error(f"{ticker:<6} | {mode:<8} | no price data — exit NOT placed")
        return

    lmt_price = round(price - 0.05, 2)
    qty = trade["quantity"]

    order_id = cp.place_limit_sell(account_id, conid, qty, lmt_price)
    if order_id:
        logger.info(
            f"{ticker:<6} | {mode:<8} | order_placed | "
            f"id={order_id} qty={qty} lmt={lmt_price} acct={account_id}"
        )
    else:
        logger.error(f"{ticker:<6} | {mode:<8} | order_place FAILED — marking EXITED")
        trade["status"] = "EXITED"
        return

    # Wait up to 30 s for fill
    for _ in range(15):
        time.sleep(2)
        status = cp.get_order_status(account_id, order_id)
        if status in ("Filled", "Cancelled", "Inactive"):
            break

    if status == "Filled":
        logger.info(
            f"{ticker:<6} | {mode:<8} | FILLED        | "
            f"qty={qty} order_id={order_id}"
        )
    else:
        logger.warning(
            f"{ticker:<6} | {mode:<8} | fill_timeout   | "
            f"status={status} order_id={order_id} — marking EXITED anyway"
        )
    trade["status"] = "EXITED"
