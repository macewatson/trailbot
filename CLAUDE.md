# CLAUDE.md — TrailBot: Smart Trailing Stop Bot for IBKR

## Project Overview

TrailBot is a headless Python daemon running on **mwuls-4** (Ubuntu 24.04, `10.0.1.10`)
that manages smart multi-stage trailing stop exits on IBKR positions via the
**IBKR Client Portal REST API** (CPAPI).

The operator (Mace) enters trades manually. TrailBot watches price action and manages
stop logic automatically — including hard stops, trailing stops, VWAP-aware tightening,
and multi-stage profit targets. Designed to run 10+ positions per day unattended.

---

## Environment

| Item | Value |
|---|---|
| Server | mwuls-4, Ubuntu 24.04 LTS |
| Server IP | 10.0.1.10 |
| Project root | `~/python_projects/trailbot/` |
| GitHub | https://github.com/macewatson/trailbot.git |
| Python | 3.11+ (system) |
| IBKR interface | **Client Portal Gateway** (REST API, NOT ib_insync) |
| CPAPI port | 5000 (HTTPS, self-signed TLS) |
| CPAPI gateway dir | `~/clientportal.gw/` |
| systemd services | `cpgateway.service` (gateway), `trailbot.service` (bot) |
| IB Gateway | Installed at `~/ibgateway/`, **disabled** — kept for future use |
| Claude Code | Installed on mwuls-4 |

## IBKR Accounts

| Account | ID | Type |
|---|---|---|
| Individual | `U20004766` | Taxable |
| Roth IRA | `U20280589` | Retirement |

Each trade is tagged with an `account` field. The `--account` flag on `addtrade` accepts `individual` or `roth` (case-insensitive). There is no default — the account must always be specified explicitly.

---

## Project File Structure

```
~/python_projects/trailbot/
├── CLAUDE.md                  ← this file
├── CHANGELOG.md               ← updated after every meaningful change
├── README.md                  ← project overview for GitHub
├── .gitignore                 ← see Git & Security section
├── .env.example               ← safe template, committed to repo
├── requirements.txt
├── trailbot.service           ← systemd unit (copy to /etc/systemd/system/)
├── cpgateway.service          ← systemd unit for Client Portal Gateway
├── bot/
│   ├── main.py                ← daemon entry point, main price loop
│   ├── trailing.py            ← multi-stage trailing stop engine (pure logic)
│   ├── vwap.py                ← VWAP calculator using CPAPI historical bars
│   └── ibkr.py                ← CpApi class + place_exit_order (REST, no ib_insync)
├── cli/
│   └── trailbot.py            ← all CLI commands (addtrade, listtrades, etc.)
├── data/
│   └── trades.json            ← shared state: CLI writes, bot reads/watches
├── logs/
│   └── trailbot.log           ← append-only trade/stop event log
└── config/
    └── settings.json          ← non-sensitive bot configuration only
```

---

## Git & Security

### .gitignore

```gitignore
# Credentials and secrets — NEVER commit these
.env
*.env
config/settings.json
/ibc/config.ini

# Live trade state (contains position data)
data/trades.json

# Logs (may contain account/price data)
logs/

# Python
__pycache__/
*.py[cod]
*.pyo
*.pyd
.Python
venv/
env/
*.egg-info/
dist/
build/
.eggs/

# OS
.DS_Store
Thumbs.db

# Editor
.vscode/
.idea/
*.swp
*.swo
```

### .env.example (safe to commit)

```env
# Copy this file to .env and fill in real values
# NEVER commit .env to git

IBKR_ACCOUNT_INDIVIDUAL=U20004766
IBKR_ACCOUNT_ROTH=U20280589
IBKR_PAPER_ACCOUNT=DUK910907
NOTIFY_EMAIL=your@email.com

# Note: No username/password — CPAPI auth is done once per day via browser at https://localhost:5000
```

### Credential rules

- Account IDs live in `.env` — loaded via `python-dotenv`
- No username/password in `.env` — Client Portal Gateway auth is browser-based (once per session)
- `config/settings.json` holds non-sensitive bot config only (poll intervals, trail defaults)
- Never hardcode credentials anywhere in source code

### Git workflow

```bash
# Initial setup (first time only)
cd ~/python_projects/trailbot
git init
git remote add origin https://github.com/macewatson/trailbot.git
git add .
git commit -m "Initial commit"
git push -u origin main
```

```bash
# After every phase or meaningful change
git add .
git commit -m "Phase X: description"
git push
```

---

## Changelog

**`CHANGELOG.md` must be updated before every `git commit`. No exceptions.**

Format:

```markdown
# Changelog

## [Unreleased]

## [0.3.0] - 2025-04-22
### Added
- VWAP-aware stop adjustment (vwap.py)
- vwap_aware flag per position in trades.json

### Changed
- Trail distance adjusted ±25% based on VWAP band position

### Fixed
- Stop level could move down on reconnect — enforced max() on reload

## [0.2.0] - 2025-04-22
### Added
- CLI commands: addtrade, listtrades, removetrade, updatetrade, botstatus, checkconn
- Atomic writes to trades.json

## [0.1.0] - 2025-04-22
### Added
- Initial project scaffold
- IB Gateway connection via ib_insync
- Hard stop monitoring loop
```

---

## Build Order

Execute phases in sequence. Commit to GitHub at the end of each phase.

### Phase 1 — Client Portal Gateway Setup

**1.1 Install Java**
```bash
sudo apt-get install -y openjdk-17-jre-headless
java -version
```

**1.2 Download and extract the Client Portal Gateway**
```bash
cd ~
mkdir -p clientportal.gw && cd clientportal.gw
# Get the current download URL from IBKR:
# https://www.interactivebrokers.com/en/trading/ib-api.php → Client Portal Web API Gateway
wget "https://download2.interactivebrokers.com/portal/clientportal.gw.zip"
unzip clientportal.gw.zip
chmod +x bin/run.sh
```

**1.3 Test startup**
```bash
cd ~/clientportal.gw
./bin/run.sh root/conf.yaml
# Then open https://localhost:5000 in a browser (SSH tunnel if headless)
# and log in with IBKR credentials
```

**1.4 systemd service** — see `cpgateway.service` in project root.

```bash
sudo cp ~/python_projects/trailbot/cpgateway.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable cpgateway && sudo systemctl start cpgateway
```

**1.5 IB Gateway (disabled, kept for future use)**

IB Gateway remains installed at `~/ibgateway/` with `ibgateway.service` disabled:
```bash
sudo systemctl stop ibgateway
sudo systemctl disable ibgateway
# Unit file is NOT deleted
```

---

### Phase 2 — Python Environment

```bash
cd ~/python_projects/trailbot
python3 -m venv venv
source venv/bin/activate
pip install requests urllib3 pandas numpy pytz watchdog click python-dotenv
pip freeze > requirements.txt
```

---

### Phase 3 — Configuration

`.env` (never committed):
```env
IBKR_ACCOUNT_INDIVIDUAL=U20004766
IBKR_ACCOUNT_ROTH=U20280589
IBKR_PAPER_ACCOUNT=DUK910907
NOTIFY_EMAIL=your@email.com
```

`config/settings.json` (never committed):
```json
{
  "cpapi": {
    "host": "127.0.0.1",
    "port": 5000
  },
  "bot": {
    "poll_interval_seconds": 5,
    "after_hours_monitoring": true,
    "use_native_stop_orders": false,
    "log_level": "INFO"
  },
  "defaults": {
    "trail_amount": 1.50,
    "tight_trail_amount": 0.75,
    "hard_stop_required": true
  },
  "notify": {
    "email_enabled": false,
    "log_to_file": true
  }
}
```

`use_native_stop_orders` must always be `false`. IBKR native stops do not trigger
in extended hours. The bot uses its own monitoring loop for all sessions.

---

### Phase 4 — trades.json Schema

Shared state file. CLI writes; bot hot-reloads via `watchdog`. Not committed to git.

```json
{
  "AAPL": {
    "ticker": "AAPL",
    "conid": 265598,
    "account": "individual",
    "exchange": "SMART",
    "currency": "USD",
    "asset_type": "STK",
    "entry_price": 213.50,
    "quantity": 100,
    "direction": "LONG",
    "hard_stop": 210.00,
    "trail_trigger": 217.00,
    "trail_amount": 1.50,
    "tighten_at": 220.00,
    "tight_trail_amount": 0.75,
    "vwap_aware": true,
    "status": "WATCHING",
    "current_stop": 210.00,
    "stop_mode": "HARD",
    "high_water_mark": 213.50,
    "added_at": "2025-04-22T09:32:00",
    "notes": ""
  }
}
```

Status values: `WATCHING` `TRAILING` `TIGHTENED` `EXITED` `PAUSED`
Stop mode values: `HARD` `TRAILING` `TIGHT`

---

### Phase 5 — CLI (`cli/trailbot.py`)

Built with `click`. Install via `pip install -e .` or symlink to PATH.

```bash
addtrade AAPL 213.50 --account individual --qty 100 --stop 210.00 --trigger 217.00 \
         --trail 1.50 --tighten 220.00 --tight-trail 0.75 --vwap

addtrade AAPL 213.50 --account roth --qty 100 --stop 210.00   # minimal, hard stop only

listtrades
listtrades --account individual    # filter by account
botstatus
updatetrade AAPL --trail 2.00 --tighten 222.00
pausetrade AAPL
removetrade AAPL
tradelog AAPL
checkconn
```

Rules:
- `--account` is required on `addtrade`. Accepted values: `individual`, `roth` (case-insensitive)
- `individual` maps to account ID `U20004766`; `roth` maps to `U20280589`
- Account ID is resolved from `.env` at order placement time — never hardcoded
- Atomic writes: write to `.tmp` then `os.replace()`
- Validate ticker via `reqContractDetails` before adding
- Confirm before `removetrade`: `"Remove AAPL from watchlist? [y/N]"`
- Human-readable terminal output only

---

### Phase 6 — Bot Daemon (`bot/main.py`)

```
1. Load .env and settings.json
2. Wait for Client Portal Gateway to be authenticated (backoff: 5→10→30→60s)
3. Load trades.json; resolve missing conids via /iserver/secdef/search
4. Start keepalive thread (POST /tickle every 60s)
5. Start watchdog on trades.json (hot-reload on change)
6. Every poll_interval_seconds for each active trade:
   a. GET /iserver/marketdata/snapshot → bid price
   b. Update high_water_mark
   c. Run trailing.py stop engine
   d. If exit triggered → place order via ibkr.py
   e. Write updated state to trades.json atomically
   f. Log all events
7. On session loss: detect via auth_status(), reconnect loop, never crash
```

---

### Phase 7 — Trailing Stop Engine (`bot/trailing.py`)

Pure function — no side effects.

```python
def process_stop(trade: dict, current_price: float, vwap: float = None) -> dict:
    """
    Returns updated trade dict. Sets exit_triggered=True if stop is hit.
    """
```

**State machine:**

```
HARD
  if price <= hard_stop → EXIT
  if price >= trail_trigger → → TRAILING

TRAILING
  hwm = max(hwm, price)
  new_stop = hwm - effective_trail
  current_stop = max(current_stop, new_stop)    ← never moves down
  if price <= current_stop → EXIT
  if price >= tighten_at → → TIGHT

TIGHT
  hwm = max(hwm, price)
  new_stop = hwm - tight_trail_amount
  current_stop = max(current_stop, new_stop)    ← never moves down
  if price <= current_stop → EXIT
```

**`current_stop = max(current_stop, new_stop)` is enforced in every state, always.**

**VWAP adjustment (when vwap_aware=true):**
```python
vwap_upper = vwap * 1.01
vwap_lower = vwap * 0.99

if price > vwap_upper:   effective_trail = trail_amount * 0.75   # tighten
elif price < vwap_lower: effective_trail = trail_amount * 1.25   # widen
else:                    effective_trail = trail_amount
```

---

### Phase 8 — VWAP Calculator (`bot/vwap.py`)

```python
class VWAPCalculator:
    def __init__(self, cp: CpApi): ...
    def get_vwap(self, ticker: str) -> float | None: ...
```

- Fetch 5-min bars via `GET /iserver/marketdata/history?period=1d&bar=5min&outsideRth=0`
- VWAP = `Σ((H+L+C)/3 × V) / Σ(V)` for bars since 09:30 ET today
- Falls back to all returned bars pre-market
- After hours: use prior session VWAP
- Cache per ticker

---

### Phase 9 — Order Execution (`bot/ibkr.py`)

```python
def place_exit_order(cp: CpApi, trade: dict) -> None:
    # LMT at bid - $0.05 via POST /iserver/account/{accountId}/orders
    # conid required — stored in trade dict
    # Account resolved from trade["account"] → .env lookup with managed-account fallback
```

- `LMT DAY` only — works in all sessions including extended hours
- conid resolved at addtrade time; stored in trades.json
- CPAPI may return confirmation question → auto-confirmed via `POST /iserver/reply/{id}`
- Log: timestamp, account, price, order ID
- Update `trades.json` to `EXITED` on fill or timeout

---

### Phase 10 — systemd Services

**`/etc/systemd/system/cpgateway.service`** (Client Portal Gateway):
```ini
[Unit]
Description=IBKR Client Portal Gateway
After=network.target

[Service]
User=mwatson
WorkingDirectory=/home/mwatson/clientportal.gw
ExecStart=/home/mwatson/clientportal.gw/bin/run.sh /home/mwatson/clientportal.gw/root/conf.yaml
Restart=on-failure
RestartSec=15
```

**`/etc/systemd/system/trailbot.service`** (bot daemon):
```ini
[Unit]
After=network.target cpgateway.service
Wants=cpgateway.service
```

```bash
# Install both services
sudo cp cpgateway.service trailbot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable cpgateway trailbot
sudo systemctl start cpgateway
# Authenticate via browser at https://localhost:5000 (once)
sudo systemctl start trailbot
```

---

## Testing Protocol

**Always test on paper account first. Authenticate gateway to paper account.**

1. Start `cpgateway.service`; log in at `https://localhost:5000` selecting Paper
2. `trailbot checkconn` — confirm `DUK910907` shown
3. `addtrade SPY 500.00 --account individual --qty 1 --stop 498.00 --trigger 502.00 --trail 1.00`
4. `botstatus` — confirm WATCHING with conid shown
5. Force a stop hit via `updatetrade SPY --stop 600.00`
6. Confirm exit order placed and logged in `logs/trailbot.log`
7. Switch to live only after paper tests pass consistently

---

## Logging Format

```
2025-04-22 14:33:01 | AAPL | TRAILING | stop_moved | old=214.50 new=215.25 hwm=216.75 price=216.80
2025-04-22 14:41:18 | AAPL | TIGHT    | stop_moved | old=215.25 new=216.10 hwm=216.85 price=216.85
2025-04-22 14:52:44 | AAPL | TIGHT    | EXIT       | stop_hit  | stop=216.10 price=216.08 | order_placed
2025-04-22 14:52:45 | AAPL | TIGHT    | FILLED     | qty=100   | fill_price=216.03
```

---

## Rules for Claude Code

- Never place live orders unless the gateway is authenticated to the live account; confirm before switching from paper
- Never use native IBKR stop orders — monitoring loop only
- Never let `current_stop` decrease for LONG positions — `max()` is enforced everywhere
- Always write `trades.json` atomically via `os.replace()`
- Always call `POST /tickle` via keepalive thread — session expires after 5 min idle
- Always handle gateway session loss with reconnect loop — never crash on unauthenticated state
- Always update `CHANGELOG.md` before every `git commit`
- Always `git add . && git commit && git push` at end of each phase
- Never log or expose `.env` contents
- All `requests` calls to the Client Portal Gateway must use `verify=False` (self-signed TLS cert)

---

## Future Phases (do not build yet)

- Morning brief engine (watchlist scan, pre-market levels)
- Signal/entry automation (VWAP crossover, volume triggers)
- Multi-leg options stop management
- Nextcloud daily report integration (mwuls-4 hosts Nextcloud)
- Morning AI config generator (populates trades.json from overnight analysis)
