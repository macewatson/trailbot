# TrailBot — Claude Code Starter Prompt

Paste this as your first message when opening the project in Claude Code.

---

You are building **TrailBot**, a smart trailing stop loss daemon for Interactive Brokers,
running headless on Ubuntu 24.04 (mwuls-4). Full specifications are in `CLAUDE.md` —
read that file first and use it as your authoritative reference for all decisions.

## Your job right now

Work through the build phases defined in `CLAUDE.md` in order, starting with **Phase 1**
(IB Gateway + IBC installation and systemd service).

## Ground rules

- Read `CLAUDE.md` completely before writing any code or running any commands
- Complete one phase fully before moving to the next
- After completing each phase: update `CHANGELOG.md`, then `git add . && git commit && git push`
- Use paper account only (`IBKR_PORT=4002`) until explicitly told to switch to live
- Never commit `.env`, `config/settings.json`, `data/trades.json`, or anything in `logs/`
- All credentials go in `.env` via `python-dotenv` — never hardcoded
- Never use native IBKR stop orders — the bot manages its own monitoring loop
- `current_stop` may never decrease for LONG positions — enforce `max()` in all states
- Write `trades.json` atomically using `os.replace()` on every update

## When you finish each phase

Tell me:
1. What was built
2. What was committed and pushed
3. What the next phase is
4. Any blockers or questions before proceeding

## If you hit a problem

- IB Gateway won't start: check `~/ibc/logs/` and report the error
- ib_insync won't connect: verify `ss -tlnp | grep 4002` and confirm gateway is running
- Anything unclear in the spec: ask before guessing

Start now with Phase 1. Read `CLAUDE.md` first.
