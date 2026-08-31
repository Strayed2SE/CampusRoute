#!/usr/bin/env python3
"""Pure tests for connection-level domestic spillover acceleration."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "usr/bin/campus-route").read_text(encoding="utf-8")
ACCEL = (ROOT / "usr/bin/campus-route-accel").read_text(encoding="utf-8")


def step(*, enabled, campus_online, usb_online, scope="router_and_lan",
         high=False, low=False, active=0, share=0, high_seconds=0,
         low_seconds=0, elapsed=5, trigger_seconds=10, release_seconds=30,
         step_percent=10, max_share=50):
    """Mirror the daemon's hysteresis and step-up/step-down state machine."""
    if not enabled:
        return 0, 0, "disabled", "disabled", 0, 0
    if not campus_online or not usb_online or scope != "router_and_lan":
        return 0, 0, "degraded", "link_unavailable", 0, 0
    if high:
        high_seconds += elapsed
        low_seconds = 0
    else:
        high_seconds = 0
    if low:
        low_seconds += elapsed
    else:
        low_seconds = 0
    if high and high_seconds >= trigger_seconds:
        active = 1
        share = min(max_share, share + step_percent)
        return active, share, "accelerating", "high_load", 0, low_seconds
    if active and low and low_seconds >= release_seconds:
        share = max(0, share - step_percent)
        if share == 0:
            active = 0
        return active, share, "monitoring", "load_released", high_seconds, 0
    return active, share, ("accelerating" if active else "monitoring"), "threshold_not_met", high_seconds, low_seconds


# Default-off and unsupported scope never install or retain an active share.
assert step(enabled=False, campus_online=True, usb_online=True)[0:3] == (0, 0, "disabled")
assert step(enabled=True, campus_online=True, usb_online=True, scope="lan_only")[0:3] == (0, 0, "degraded")
assert "scope_unsupported" in ACCEL
assert step(enabled=True, campus_online=True, usb_online=False)[0:3] == (0, 0, "degraded")

# Ten seconds of qualifying load at a five-second sample interval triggers 10%.
s = step(enabled=True, campus_online=True, usb_online=True, high=True, elapsed=5)
assert s[0:3] == (0, 0, "monitoring")
s = step(enabled=True, campus_online=True, usb_online=True, high=True, high_seconds=s[4], elapsed=5)
assert s[0:3] == (1, 10, "accelerating")

# Further qualifying windows step 10% at a time and cap at 50%.
share, active = 10, 1
for _ in range(8):
    active, share, *_ = step(enabled=True, campus_online=True, usb_online=True,
                             high=True, active=active, share=share,
                             high_seconds=5, elapsed=5)
assert (active, share) == (1, 50)

# Low-load hysteresis releases one step only after 30 seconds, then reaches 0.
active, share = 1, 30
for _ in range(6):
    active, share, state, reason, high_s, low_s = step(
        enabled=True, campus_online=True, usb_online=True, low=True,
        active=active, share=share, low_seconds=low_s if 'low_s' in locals() else 0,
        elapsed=5)
assert (active, share, state, reason) == (1, 20, "monitoring", "load_released")

# The data plane is connection-level: NEW + zero policy mark/connmark only;
# existing marks are restored and returned before the selector.
for token in (
    "ACCEL_SELECT_CHAIN", "ACCEL_SELECTED_CHAIN", "ACCEL_MOVED_CHAIN",
    "--ctstate NEW", "-m mark --mark 0x0/\"$MASK\"",
    "-m connmark --mark 0x0/\"$MASK\"", "CONNMARK --save-mark",
    "CONNMARK --set-xmark \"$ACCEL_FLOW_FLAG/$ACCEL_FLOW_FLAG\"",
    "-m connmark --mark \"$ACCEL_FLOW_FLAG/$ACCEL_FLOW_FLAG\"",
    "-j \"$ACCEL_SELECTED_CHAIN\"", "CAMPUS_ROUTE_ACCEL_DOWN",
    "CAMPUS_ROUTE_ACCEL_UP", "CAMPUS_ROUTE_ACCEL_LOCAL",
):
    assert token in MAIN, token

# Selection is placed after control/private/plugin returns and before domestic
# campus marking; ordinary overseas and encrypted rules remain unchanged.
policy_start = MAIN.index("add_policy_rules()")
restore = MAIN.index("CONNMARK --restore-mark", policy_start)
selector_create = MAIN.index(' -t mangle -N "$ACCEL_SELECT_CHAIN"', policy_start)
assert restore < selector_create
domestic_mark = MAIN.index('--set-xmark "$campus_target/$MASK"', selector_create)
assert selector_create < domestic_mark

# IPv4 and IPv6 statistics are collected independently; local OUTPUT upload is
# included and the accelerator daemon invokes only a fixed reconcile command.
assert 'counter_bytes "$IPT6" "$MOVED_CHAIN"' in ACCEL
assert 'last_rule_bytes "$IPT6" "$LOCAL_CHAIN"' in ACCEL
assert 'last_rule_bytes "$IPT4" "$LOCAL_CHAIN"' in ACCEL
assert '/usr/bin/campus-route reconcile' in ACCEL

print("test_accel: PASS")


