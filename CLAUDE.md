# CLAUDE.md — TrailBot: Smart Trailing Stop Bot for IBKR

## Project Overview

TrailBot is a headless Python daemon running on **mwuls-4** (Ubuntu 24.04, `10.0.1.10`)
that manages smart multi-stage trailing stop exits on IBKR positions via IB Gateway.

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
| IBKR interface | IB Gateway (headless, NOT TWS) |
| IB Gateway port | 4001 (live) / 4002 (paper) |
| IBC config | `~/ibc/config.ini` |
| systemd service | `trailbot.service` |
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
├── bot/
│   ├── main.py                ← daemon entry point, main price loop
│   ├── trailing.py            ← multi-stage trailing stop engine
│   ├── vwap.py                ← real-time VWAP calculator
│   ├── ibkr.py                ← ib_insync connection + order wrapper
│   └── notify.py              ← logging + email/console alerts
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

IBKR_USERNAME=your_username_here
IBKR_PASSWORD=your_password_here
IBKR_ACCOUNT_INDIVIDUAL=U20004766
IBKR_ACCOUNT_ROTH=U20280589
IBKR_PORT=4002
NOTIFY_EMAIL=your@email.com
```

### Credential rules

- All credentials live in `.env` only — loaded via `python-dotenv`
- `config/settings.json` holds non-sensitive bot config only (poll intervals, trail defaults)
- Never hardcode credentials anywhere in source code
- Never log, print, or expose `.env` or `config.ini` contents

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

### Phase 1 — IB Gateway + IBC (Unattended Login)

**1.1 Download IB Gateway**
```bash
cd ~
mkdir -p ibgateway && cd ibgateway
wget "https://download2.interactivebrokers.com/installers/ibgateway/stable-standalone/ibgateway-stable-standalone-linux-x64.sh"
chmod +x ibgateway-stable-standalone-linux-x64.sh
./ibgateway-stable-standalone-linux-x64.sh -q
```

**1.2 Install IBC**
```bash
cd ~
mkdir -p ibc && cd ibc
wget "https://github.com/IbcAlpha/IBC/releases/latest/download/IBCLinux-3.18.0.zip"
unzip IBCLinux-3.18.0.zip
chmod +x *.sh
```

**1.3 Configure IBC**

Create `~/ibc/config.ini` — load credentials from `.env`:
```ini
IbLoginId=${IBKR_USERNAME}
IbPassword=${IBKR_PASSWORD}
TradingMode=paper
IbDir=/root/Jts/ibgateway/1019
ReadonlyLogin=no
AcceptIncomingConnectionAction=accept
SendTWSTelemetryUsageStatistics=no
```

**1.4 Test startup**
```bash
cd ~/ibc && ./gatewaystart.sh
ss -tlnp | grep 4002
```

**1.5 systemd service for IB Gateway**

`/etc/systemd/system/ibgateway.service`:
```ini
[Unit]
Description=IB Gateway (headless)
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/ibc
ExecStart=/root/ibc/gatewaystart.sh
Restart=always
RestartSec=30
StandardOutput=append:/root/ibc/logs/gateway.log
StandardError=append:/root/ibc/logs/gateway-err.log

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload && systemctl enable ibgateway && systemctl start ibgateway
```

---

### Phase 2 — Python Environment

```bash
cd ~/python_projects/trailbot
python3 -m venv venv
source venv/bin/activate
pip install ib_insync pandas numpy pytz watchdog click python-dotenv
pip freeze > requirements.txt
```

---

### Phase 3 — Configuration

`.env` (never committed):
```env
IBKR_USERNAME=your_username
IBKR_PASSWORD=your_password
IBKR_ACCOUNT_INDIVIDUAL=U20004766
IBKR_ACCOUNT_ROTH=U20280589
IBKR_PORT=4002
NOTIFY_EMAIL=your@email.com
```

`config/settings.json` (never committed):
```json
{
  "ibkr": {
    "host": "127.0.0.1",
    "port": 4002,
    "client_id": 1,
    "readonly": false
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
2. Connect to IB Gateway via ib_insync
3. Load trades.json
4. Start watchdog on trades.json (hot-reload on change)
5. Every poll_interval_seconds for each active trade:
   a. Get current bid price from IBKR
   b. Update high_water_mark
   c. Run trailing.py stop engine
   d. If exit triggered → place order via ibkr.py
   e. Write updated state to trades.json atomically
   f. Log all events
6. On disconnect: backoff reconnect (5s → 10s → 30s → 60s), never crash
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
    def __init__(self, ticker: str, ib): ...
    def get_vwap(self) -> float: ...
```

- Fetch bars from session open (09:30 ET US equities) via `reqHistoricalData`
- Live updates via `reqRealTimeBars`
- After hours: use prior session VWAP
- Cache per ticker

---

### Phase 9 — Order Execution (`bot/ibkr.py`)

```python
def place_exit_order(ib, trade: dict) -> None:
    # LMT at bid - $0.05. Bot triggers — no native IBKR stops.
    # Account resolved from trade["account"] via get_account_id()
```

- `LimitOrder` only — works in all sessions including extended hours
- Account ID resolved via `get_account_id(account_label)`: `individual` → `IBKR_ACCOUNT_INDIVIDUAL`, `roth` → `IBKR_ACCOUNT_ROTH`
- Log: timestamp, account, price, reason, order ID
- Update `trades.json` to `EXITED` on fill
- Handle partial fills

Asset routing:
- `STK` → SMART
- `OPT` → requires expiry, strike, right — handle separately
- `CASH` (FX) → IDEALPRO
- Euro equities → explicit exchange (IBIS, AEB, etc.) — never SMART

---

### Phase 10 — TrailBot systemd Service

`/etc/systemd/system/trailbot.service`:
```ini
[Unit]
Description=TrailBot Smart Trailing Stop Daemon
After=network.target ibgateway.service
Requires=ibgateway.service

[Service]
Type=simple
User=mwatson
WorkingDirectory=/home/mwatson/python_projects/trailbot
ExecStart=/home/mwatson/python_projects/trailbot/venv/bin/python bot/main.py
Restart=always
RestartSec=10
StandardOutput=append:/home/mwatson/python_projects/trailbot/logs/trailbot.log
StandardError=append:/home/mwatson/python_projects/trailbot/logs/trailbot-err.log
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload && systemctl enable trailbot && systemctl start trailbot
```

---

## Testing Protocol

**Always test on paper account first. `IBKR_PORT=4002` in `.env`.**

1. `checkconn` — confirm connection
2. `addtrade SPY 500.00 --account individual --qty 1 --stop 498.00 --trigger 502.00 --trail 1.00`
3. `botstatus` — confirm watching
4. Force a stop hit via `updatetrade` — lower stop to current price
5. Confirm exit order placed and logged
6. Review `logs/trailbot.log`
7. Switch to live (`IBKR_PORT=4001`) only after paper tests pass consistently

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

- Never place live orders without confirming `IBKR_PORT=4002` unless explicitly told to go live
- Never use native IBKR stop orders — monitoring loop only
- Never let `current_stop` decrease for LONG positions — `max()` is enforced everywhere
- Always write `trades.json` atomically via `os.replace()`
- Always handle IB Gateway disconnects with reconnect loop — never crash on disconnect
- Always update `CHANGELOG.md` before every `git commit`
- Always `git add . && git commit && git push` at end of each phase
- Never log or expose `.env` or `config.ini` contents
- Euro equities and FX require explicit exchange routing — never assume SMART

---

## Future Phases (do not build yet)

- Morning brief engine (watchlist scan, pre-market levels)
- Signal/entry automation (VWAP crossover, volume triggers)
- Multi-leg options stop management
- Nextcloud daily report integration (mwuls-4 hosts Nextcloud)
- Morning AI config generator (populates trades.json from overnight analysis)
