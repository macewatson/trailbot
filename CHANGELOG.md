# Changelog

## [Unreleased]

## [0.1.0] - 2026-04-22
### Added
- Phase 1: IB Gateway 10.37 + IBC 3.23.0 installation on mwuls-4
- `.gitignore` protecting credentials, logs, trade state, and settings
- `.env.example` credential template
- `ibgateway.service` systemd unit (User=mwatson, calls ~/ibc/start.sh)
- `~/ibc/config.ini.template` with `${IBKR_USERNAME}` / `${IBKR_PASSWORD}` placeholders
- `~/ibc/start.sh` wrapper: sources `.env`, runs envsubst to generate config.ini, launches gatewaystart.sh -inline
- IBC `gatewaystart.sh` configured: TWS_MAJOR_VRSN=1037, IBC_PATH=~/ibc, TWS_PATH=~/ibgateway
