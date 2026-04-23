# Changelog

## [Unreleased]

## [0.1.0] - 2026-04-22
### Added
- Phase 1: IB Gateway 10.37 + IBC 3.23.0 installation on mwuls-4
- `.gitignore` protecting credentials, logs, trade state, and settings
- `.env.example` credential template
- `ibgateway.service` systemd unit (User=mwatson, calls ~/ibc/start.sh)
- `~/ibc/config.ini.template` with `${IBKR_USERNAME}` / `${IBKR_PASSWORD}` placeholders
- `~/ibc/start.sh` wrapper: sources `.env`, runs envsubst to generate config.ini, restores IBC-renamed symlinks, launches Xvfb + gatewaystart.sh -inline
- IBC `gatewaystart.sh` configured: TWS_MAJOR_VRSN=1037, IBC_PATH=~/ibc, TWS_PATH=~/ibgateway, JAVA_PATH=Zulu JRE bundled by installer

### Fixed
- Created `~/ibgateway/1037/` symlink directory (IBC expects versioned path; installer puts files flat)
- Added `.install4j/` symlink so `i4jruntime.jar` is on classpath
- Added `tws.vmoptions` symlink (IBC fallback after jars-dir swap)
- Set JAVA_PATH to Zulu JRE bundled by installer (includes JavaFX; system JDK does not)
- Installed missing system libs: `openjdk-17-jre-headless`, `xvfb`, `libxtst6`, `libxi6`
