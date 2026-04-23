# CPAPI Migration Plan — IB Gateway → Client Portal Gateway

**Status**: Implementation complete as of 2026-04-23  
**Version**: 1.0.0

---

## Why Migrate

IB Gateway (TWS protocol, port 4001/4002) is being disabled. The replacement is
the **IBKR Client Portal Gateway** — a separate Java process that exposes a REST
API on port 5000 (HTTPS, self-signed cert). The ib_insync Python library is
eliminated entirely; all communication becomes plain `requests` calls.

**Key benefit**: No session conflicts with IBKR Desktop. The Client Portal
Gateway runs a dedicated auth session that does not fight with the Desktop app
(each user can have multiple IBKR usernames sharing the same account).

---

## Architecture Before → After

### Before (IB Gateway + ib_insync)

```
[IBC/Xvfb auto-login]
       ↓
[IB Gateway :4002]  ← TCP, TWS protocol
       ↓
[ib_insync IB()]    ← event loop, subscriptions
       ↓
[TrailBot]
```

### After (Client Portal Gateway + requests)

```
[Manual browser auth (once per day)]
       ↓
[Client Portal Gateway :5000]  ← HTTPS REST, self-signed TLS
       ↓
[requests.Session + keepalive thread]
       ↓
[TrailBot]
```

---

## Client Portal Gateway — Installation (Ubuntu 24.04)

### 1. Install Java (if not present)

```bash
sudo apt-get install -y openjdk-17-jre-headless
java -version
```

### 2. Download the Gateway

```bash
cd ~
mkdir -p clientportal.gw && cd clientportal.gw
# Download from IBKR — get the current URL from:
# https://www.interactivebrokers.com/en/trading/ib-api.php
# Look for "Client Portal Web API Gateway" download
wget "https://download2.interactivebrokers.com/portal/clientportal.gw.zip"
unzip clientportal.gw.zip
chmod +x bin/run.sh
```

### 3. Configure conf.yaml

The gateway reads `root/conf.yaml` (already present after unzip). Default settings
are fine for paper trading. Key fields:

```yaml
listenPort: 5000
listenSsl: true
```

For paper trading: no change needed — account selection happens at login time.

### 4. First-time authentication

The gateway itself has no headless auth like IBC. Each session requires one
manual browser login:

1. Start the gateway process:
   ```bash
   cd ~/clientportal.gw
   ./bin/run.sh root/conf.yaml
   ```

2. Open a browser (on the server or via SSH tunnel) to:
   `https://localhost:5000`

3. Accept the self-signed certificate warning.

4. Log in with your IBKR credentials. Select "Paper" if testing.

5. Session persists until midnight (ET/Zug/HK) or gateway restart.

### 5. systemd service

Copy `cpgateway.service` from the project root:

```bash
sudo cp ~/python_projects/trailbot/cpgateway.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable cpgateway
sudo systemctl start cpgateway
```

The gateway starts automatically. After each gateway restart, you must
re-authenticate via browser once.

### 6. SSH tunnel for browser auth (headless server)

Since mwuls-4 is headless, tunnel port 5000 to your local machine:

```bash
# On your local Mac/PC:
ssh -L 5000:localhost:5000 mwatson@10.0.1.10
```

Then open `https://localhost:5000` in your local browser.

### 7. Disable (but keep) ibgateway.service

```bash
sudo systemctl stop ibgateway
sudo systemctl disable ibgateway
# Service unit file is NOT deleted — kept for future reference
```

---

## Client Portal API — Endpoints Used by TrailBot

Base URL: `https://localhost:5000/v1/api`  
TLS: self-signed — all `requests` calls use `verify=False`  
Auth: session cookie, maintained by `POST /tickle` every 60 s

### Session / Auth

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/tickle` | Session keepalive (call every 60 s) |
| GET | `/iserver/auth/status` | Check authentication state |

`/tickle` must be called at least every 5 minutes or the session expires.
TrailBot calls it every 60 s from a background thread.

### Accounts

| Method | Path | Notes |
|--------|------|-------|
| GET | `/iserver/accounts` | List account IDs. Requires double-call (preflight). |

Response shape:
```json
{"accounts": ["DUK910907"], "selectedAccount": "DUK910907"}
```

### Contract Lookup (conid resolution)

| Method | Path | Body |
|--------|------|------|
| POST | `/iserver/secdef/search` | `{"symbol": "AAPL", "name": false, "secType": "STK"}` |

Returns list of matching contracts. Use `conid` from the first `STK` match.
conids are stable — cached in-process and stored in `trades.json`.

```json
[{"conid": 265598, "companyName": "APPLE INC", "assetClass": "STK", ...}]
```

### Market Data Snapshot

| Method | Path | Key Params |
|--------|------|-----------|
| GET | `/iserver/marketdata/snapshot` | `conids={conid}`, `fields=84,31,86` |

Field codes:
- `31` = Last trade price
- `84` = Bid price  ← TrailBot uses this for exit pricing
- `86` = Ask price

**Quirk**: The first snapshot request for a new conid initiates a subscription
and returns no data. The second call (≥200 ms later) returns live quotes.
TrailBot's 5-second poll interval naturally handles this — first tick skipped,
all subsequent ticks have live data.

Response (list with one dict per conid):
```json
[{"conid": 265598, "84": "213.45", "31": "213.50", "86": "213.55"}]
```

### Historical Bars (for VWAP)

| Method | Path | Key Params |
|--------|------|-----------|
| GET | `/iserver/marketdata/history` | `conid`, `period=1d`, `bar=5min`, `outsideRth=0` |

Response:
```json
{
  "data": [
    {"t": 1713794400000, "o": 213.50, "h": 214.10, "l": 213.20, "c": 213.75, "v": 12345},
    ...
  ]
}
```

`t` is Unix timestamp in milliseconds. VWAP is computed as:
```
VWAP = Σ((H+L+C)/3 × V) / Σ(V)   for bars since 09:30 ET today
```

### Order Placement

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/iserver/account/{accountId}/orders` | Place order |
| GET | `/iserver/account/{accountId}/orders` | List open/recent orders |

Order request body:
```json
{
  "orders": [{
    "conid": 265598,
    "orderType": "LMT",
    "side": "SELL",
    "quantity": 100,
    "price": 213.40,
    "tif": "DAY",
    "cOID": "TB_265598_1713794400"
  }]
}
```

**Confirmation flow**: CPAPI may return a question dict requiring acknowledgement
before the order is submitted:
```json
[{"id": "confirm-uuid", "message": ["Order warning text"], "isSuppressed": false}]
```
TrailBot auto-confirms via `POST /iserver/reply/{id}` with `{"confirmed": true}`.

Order status values: `PreSubmitted`, `Submitted`, `Filled`, `Cancelled`, `Inactive`

---

## Session Management

| Aspect | Detail |
|--------|--------|
| Max session duration | 24 hours (resets at midnight ET/Zug/HK) |
| Inactivity timeout | ~5 minutes without any request |
| Keepalive call | `POST /tickle` — TrailBot calls every 60 s |
| After midnight | Gateway session expires; bot detects unauthenticated state and waits for re-auth |
| IBKR Desktop conflict | Cannot share session with same username. Use Gateway exclusively, or create a dedicated API username via IBKR Account Management. |

---

## Code Changes Summary

| File | Change |
|------|--------|
| `bot/ibkr.py` | Full rewrite: `CpApi` class + `place_exit_order(cp, trade)` |
| `bot/main.py` | Full rewrite: remove ib_insync, add keepalive thread, poll-based pricing |
| `bot/vwap.py` | Updated: CPAPI historical bars; VWAP computed from (H+L+C)/3 |
| `bot/trailing.py` | **Untouched** — pure logic, no connection dependency |
| `cli/trailbot.py` | `connect_ib()` → `connect_cp()`; conid stored in trades.json |
| `config/settings.json` | `ibkr` section → `cpapi` section (host + port only) |
| `.env.example` | Removed `IBKR_USERNAME/PASSWORD`; added `IBKR_PAPER_ACCOUNT` |
| `trailbot.service` | `Wants=ibgateway.service` → `Wants=cpgateway.service` |
| `cpgateway.service` | New: systemd unit for Client Portal Gateway |
| `requirements.txt` | Removed `ib-insync`, added `requests` |
| `CLAUDE.md` | Architecture section updated |

---

## New trades.json Field: conid

Each trade entry now stores `conid` (the IBKR numeric contract ID):

```json
{
  "AAPL": {
    "conid": 265598,
    ...
  }
}
```

`conid` is resolved at `addtrade` time via `/iserver/secdef/search` and stored
permanently. The bot also re-resolves on startup for any trade missing a conid.
Existing `trades.json` entries without `conid` are automatically resolved.

---

## Paper Account Testing

Paper account: **DUK910907**

1. Start cpgateway.service
2. Authenticate via browser, selecting "Paper Trading"
3. `trailbot checkconn` — should show `DUK910907`
4. `addtrade SPY 500.00 --account individual --qty 1 --stop 498.00`
5. `botstatus` — confirm WATCHING
6. `updatetrade SPY --stop 600.00` to force exit
7. Confirm order logged in `logs/trailbot.log`

---

## Rollback

IB Gateway is disabled but NOT deleted. To revert:

```bash
sudo systemctl stop trailbot cpgateway
sudo systemctl disable cpgateway
sudo systemctl enable ibgateway
sudo systemctl start ibgateway
# Restore old bot/ibkr.py, bot/main.py, bot/vwap.py from git
git checkout <commit-before-migration> -- bot/ibkr.py bot/main.py bot/vwap.py cli/trailbot.py config/settings.json
```
