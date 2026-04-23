# Changelog

## [Unreleased]

## [1.0.0] - 2026-04-23
### Changed (Breaking — full architecture migration)
- **Transport**: IB Gateway (TWS protocol, ib_insync) → IBKR Client Portal Gateway (REST API, `requests`)
- `bot/ibkr.py`: Full rewrite — `CpApi` class wrapping CPAPI REST endpoints; `place_exit_order(cp, trade)` uses `/iserver/account/{accountId}/orders`; auto-confirms CPAPI order confirmation questions; `resolve_account()` falls back to first managed account if configured ID not in managed list
- `bot/main.py`: Full rewrite — removes ib_insync IB object and market-data subscriptions; adds keepalive background thread (`POST /tickle` every 60 s); conid resolution on startup/hot-reload; poll-based snapshot pricing via `CpApi.get_price()`; `connect_cpapi()` waits for gateway auth with backoff
- `bot/vwap.py`: Updated — uses `CpApi.get_historical_bars()` instead of `reqHistoricalData`; VWAP computed as `Σ((H+L+C)/3 × V) / Σ(V)` (CPAPI bars lack per-bar VWAP); filters to 09:30 ET session open by timestamp; signature changed to `get_vwap(ticker)` (no exchange/currency args — uses conid cache)
- `cli/trailbot.py`: `connect_ib()` → `connect_cp()`; `addtrade` validates ticker via `CpApi.resolve_conid()` and stores `conid` in trades.json; `checkconn` shows CPAPI auth status
- `config/settings.json`: `ibkr` section replaced by `cpapi` with `host` + `port` (5000) only; `client_id` / `cli_client_id` removed (not applicable to REST API)
- `.env.example`: Removed `IBKR_USERNAME` / `IBKR_PASSWORD` (CPAPI auth is browser-based); added `IBKR_PAPER_ACCOUNT`
- `trailbot.service`: `Wants=ibgateway.service` → `Wants=cpgateway.service`
- `requirements.txt`: Removed `ib-insync`, `eventkit`, `nest-asyncio`; added `requests`, `urllib3`

### Added
- `cpgateway.service`: systemd unit for IBKR Client Portal Gateway (runs `~/clientportal.gw/bin/run.sh`)
- `docs/cpapi-migration.md`: Full migration plan — gateway install, auth flow, all CPAPI endpoints used, session management, paper testing guide, rollback procedure
- `conid` field in trades.json: IBKR numeric contract ID stored at `addtrade` time; bot auto-resolves on startup for existing entries

### Unchanged
- `bot/trailing.py`: Pure stop-engine logic — untouched

### Removed
- `ibgateway.service` dependency from trailbot.service (service unit file kept on disk, disabled)
- IBC / Xvfb auto-login stack (no longer needed — CPAPI uses browser auth)

## [0.5.1] - 2026-04-22
### Changed
- `~/ibc/config.ini.template`: `AutoRestartTime` changed from 04:00 to 02:50 ET to restart after the IBKR maintenance window (typically ends ~02:45 ET); removed `ClosedownAt` — bot runs 24/7 with no planned Friday shutdown

## [0.5.0] - 2026-04-22
### Added
- `addtrade`: `--trail-pct` and `--tight-trail-pct` options — calculates dollar amount from entry price at add time; stores both `trail_amount` and `trail_pct` (null if dollar mode) in trades.json
- `updatetrade`: same `--trail-pct` / `--tight-trail-pct` options using existing trade's `entry_price`; switching to dollar mode clears stored pct and vice versa
- `botstatus`: expanded from count-only summary to per-trade table showing TRAIL and TIGHT TRAIL with `(X%)` annotation when pct mode was used

## [0.4.0] - 2026-04-22
### Added
- `~/ibc/config.ini.template`: full 2FA configuration — `SecondFactorDevice`, `ReloginAfterSecondFactorAuthenticationTimeout`, `AutoRestartTime` (04:00 ET), `ClosedownAt` (Friday 21:00), `ExistingSessionDetectedAction=primaryoverride`, `AcceptNonBrokerageAccountWarning=yes`
- `docs/ibc-2fa-setup.md`: manual IBKR account steps for headless 2FA (IBKR Mobile registration, Gateway auto-restart UI config, troubleshooting)

## [0.3.0] - 2026-04-22
### Added
- Phase 6: `bot/main.py` — daemon with poll loop, watchdog hot-reload, reconnect backoff (5→10→30→60s)
- Phase 7: `bot/trailing.py` — pure stop engine: HARD/TRAILING/TIGHT state machine, VWAP adjustment, `max()` enforced everywhere
- Phase 8: `bot/vwap.py` — VWAPCalculator using `reqHistoricalData` (5-min bars, RTH); 60s cache per ticker; handles pre-market (uses prior session) and after-hours; integrated into main loop for `vwap_aware` trades
- Phase 9: `bot/ibkr.py` — `place_exit_order`: LMT at bid−$0.05, routes to correct account via `get_account_id()`, 30s fill wait, logs `order_placed` + `FILLED`/`fill_timeout`
- Phase 10: `trailbot.service` systemd unit — starts after `ibgateway.service`, `Restart=always`, `RestartSec=15`

### Tested
- Full E2E paper trade: SPY added via CLI, hot-reload detected, hard stop triggered (stop=750.00 price=708.49), order placed on DUK910907 (lmt=708.44), trade marked EXITED. Order cancelled by IBKR because market was closed — correct DAY order behavior.

### Changed
- Phase 10 systemd unit corrected to use `User=mwatson` and `/home/mwatson/` paths

## [0.2.0] - 2026-04-22
### Added
- Phase 2: Python 3.12 venv + dependencies (ib_insync 0.9.86, pandas, numpy, watchdog, click, python-dotenv); `requirements.txt` generated from venv
- Phase 3: `config/settings.json` with IBKR connection, bot poll, trail defaults, notify settings
- Phase 4: `data/trades.json` schema with `account` field; atomic write via `os.replace()`
- Phase 5: `cli/trailbot.py` — all CLI commands: `addtrade`, `listtrades`, `updatetrade`, `pausetrade`, `resumetrade`, `removetrade`, `tradelog`, `botstatus`, `checkconn`
- `pyproject.toml` entry point — `pip install -e .` installs `trailbot` command
- `--account individual|roth` required on `addtrade`; resolves to account ID from `.env` at order time
- Ticker validation via `reqContractDetails` before adding to watchlist

### Changed
- Two-account support: Individual `U20004766`, Roth IRA `U20280589`
- `.env` split `IBKR_ACCOUNT` into `IBKR_ACCOUNT_INDIVIDUAL` and `IBKR_ACCOUNT_ROTH`

## [0.1.0] - 2026-04-22
### Added
- Phase 1: IB Gateway 10.37 + IBC 3.23.0 installation on mwuls-4
- `.gitignore` protecting credentials, logs, trade state, and settings
- `.env.example` credential template
- `ibgateway.service` systemd unit (User=mwatson, calls `~/ibc/start.sh`)
- `~/ibc/config.ini.template` with `${IBKR_USERNAME}` / `${IBKR_PASSWORD}` placeholders
- `~/ibc/start.sh` wrapper: sources `.env`, runs `envsubst` to generate `config.ini`, restores IBC-renamed symlinks, launches Xvfb + `gatewaystart.sh -inline`
- IBC `gatewaystart.sh` configured: `TWS_MAJOR_VRSN=1037`, `IBC_PATH=~/ibc`, `TWS_PATH=~/ibgateway`, `JAVA_PATH` set to Zulu JRE bundled by installer

### Fixed
- Created `~/ibgateway/1037/` symlink directory (IBC expects versioned path; installer puts files flat)
- Added `.install4j/` symlink so `i4jruntime.jar` is on classpath
- Added `tws.vmoptions` symlink (IBC fallback after jars-dir swap)
- Set `JAVA_PATH` to Zulu JRE bundled by installer (includes JavaFX; system JDK does not)
- Installed missing system libs: `openjdk-17-jre-headless`, `xvfb`, `libxtst6`, `libxi6`
