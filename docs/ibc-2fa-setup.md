# IBC 2FA Setup for Headless IB Gateway

TrailBot runs IB Gateway unattended on mwuls-4. This document covers the
required IBKR account configuration and IBC settings to make 2FA work
with minimal manual intervention.

## How IBC Handles 2FA

IBKR cannot disable 2FA — it is mandatory for all accounts. IBC works around
daily re-authentication using the **AutoRestart** mechanism:

- Gateway restarts at `AutoRestartTime` (04:00 ET) every weekday morning
- AutoRestart **reuses existing session credentials** — no 2FA prompt fires
- 2FA is only required **once per week**: Monday morning when starting a
  fresh session (or after any unplanned session expiry)
- On Friday evening (`ClosedownAt=Friday 21:00`), IBC shuts down cleanly;
  the session expires naturally over the weekend

**Weekly routine:** SSH into mwuls-4 on Monday morning, run
`systemctl start ibgateway`, tap Approve in IBKR Mobile when prompted.
That's it for the week.

---

## Part 1: IBKR Account Steps (manual, done once)

### 1. Install and register IBKR Mobile as your 2FA device

IBKR Mobile (IB Key) is the only 2FA method that works reliably with IBC
on a headless server. Hardware tokens and SMS require manual input.

1. Install **IBKR Mobile** on your phone (iOS or Android)
2. Open IBKR Mobile → tap the prominent **"Activate IB Key"** button
3. Log in with your IBKR credentials when prompted
4. The app is now registered as a 2FA device for your account

### 2. Note the exact device name IBC must match

When IB Gateway shows the 2FA device-selection screen, it lists registered
devices by name. The `SecondFactorDevice` setting in `config.ini` must match
this name exactly (case-sensitive).

To find it: log into IB Gateway manually once (`~/ibc/gatewaystart.sh`),
watch the login screen, and note the text of your device in the list.
The value is almost always **`IBKR Mobile`** for the mobile app.

If you have multiple 2FA devices (e.g., mobile app + hardware token),
set `SecondFactorDevice` to the mobile app entry so IBC auto-selects it.
If you only have one device, IBC auto-selects it regardless.

### 3. (Optional but recommended) Remove extra 2FA devices

If old or unused devices appear in the selection list, remove them at:
**IBKR Account Management → Settings → Security → Secure Login System**

Fewer devices = cleaner auto-selection and less risk of IBC selecting the
wrong one.

### 4. Verify paper account access

Log into the paper account at least once manually to confirm your credentials
work and the paper account is active. IBC's `AcceptNonBrokerageAccountWarning=yes`
handles the paper-account warning dialog automatically on all subsequent logins.

---

## Part 2: Gateway UI Configuration (manual, done once after installation)

The `AutoRestartTime` setting in `config.ini` requires a matching entry in
Gateway's own configuration — IBC cannot set this via config alone.

### Set the Auto-Restart time in Gateway

1. Start Gateway and log in manually
2. Open **Global Configuration** (gear icon or File → Global Configuration)
3. Navigate to **Lock and Exit** (left sidebar)
4. Find **Auto logoff time** and set it to `04:00` (or match your `AutoRestartTime`)
5. Ensure **Auto restart** is enabled (checkbox), not just auto-logoff
6. Click **OK** and close the dialog

Without this step, Gateway will log off at 04:00 but IBC will not restart it.

---

## Part 3: IBC config.ini Settings Summary

All settings are in `~/ibc/config.ini.template`. Key 2FA-related values:

| Setting | Value | Purpose |
|---|---|---|
| `SecondFactorDevice` | `IBKR Mobile` | Auto-selects mobile app from device list |
| `SecondFactorAuthenticationTimeout` | `180` | IBKR's timeout (do not change) |
| `SecondFactorAuthenticationExitInterval` | `60` | Wait after app approval tap |
| `ReloginAfterSecondFactorAuthenticationTimeout` | `yes` | Retry if push notification missed |
| `AutoRestartTime` | `04:00` | Daily restart (no 2FA required) |
| `ClosedownAt` | `Friday 21:00` | Clean shutdown for weekend |
| `ExistingSessionDetectedAction` | `primaryoverride` | Handles stale sessions on restart |
| `AcceptNonBrokerageAccountWarning` | `yes` | Dismisses paper account dialog |

---

## Troubleshooting

**Gateway stuck at 2FA screen on startup:**
The push notification may have expired before you tapped it. With
`ReloginAfterSecondFactorAuthenticationTimeout=yes`, IBC retries automatically
and sends a new push. Wait ~3 minutes and check your phone again.

**Multiple 2FA device prompts (two accounts):**
If running paper and live Gateway simultaneously, schedule their restarts at
different times to avoid concurrent 2FA prompts. TrailBot uses paper only
(`TradingMode=paper`) so this is not an issue in the current setup.

**`ExistingSessionDetectedAction` dialog appears:**
Happens if IBKR Mobile or Client Portal terminated the Gateway session
(e.g., you checked a balance on your phone). `primaryoverride` handles this
automatically — no action needed.

**Session expires mid-week:**
Rare, but IBKR can invalidate sessions (maintenance, security event). Restart
ibgateway.service manually: `systemctl restart ibgateway`. You will get a
fresh 2FA prompt — tap Approve in IBKR Mobile.

**`SecondFactorDevice` doesn't match:**
The device name is case-sensitive. Log in manually once, note the exact text
in the selection list, and update `SecondFactorDevice` in `config.ini.template`.
Regenerate `config.ini` by restarting ibgateway.service.
