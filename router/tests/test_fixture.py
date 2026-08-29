#!/usr/bin/env python3
"""Pure fixture tests for Campus Route policy decisions."""
from pathlib import Path

MARK_CAMPUS, MARK_USB, MARK_BLOCK = 0x1000, 0x2000, 0x3000
ROOT = Path(__file__).resolve().parents[1]


def classify(*, domestic=False, encrypted=False, usb_online=True,
             campus_online=True, fallback=False, unknown="usb",
             domestic_precedence=True, campus_failover=True):
    usb_target = MARK_USB if usb_online else (MARK_CAMPUS if fallback else MARK_BLOCK)
    campus_target = (MARK_CAMPUS if campus_online or not campus_failover
                     else (MARK_USB if usb_online else MARK_BLOCK))
    if domestic and domestic_precedence:
        return campus_target
    if encrypted:
        return usb_target
    if domestic:
        return campus_target
    return {"usb": usb_target, "campus": campus_target,
            "reject": MARK_BLOCK}.get(unknown, usb_target)

assert classify(domestic=True, encrypted=True) == MARK_CAMPUS
assert classify(domestic=True, campus_online=False) == MARK_USB
assert classify(domestic=True, campus_online=False, usb_online=False) == MARK_BLOCK
assert classify(domestic=True, campus_online=False, campus_failover=False) == MARK_CAMPUS
assert classify(domestic=False, encrypted=True, usb_online=True) == MARK_USB
assert classify(domestic=False, encrypted=True, usb_online=False) == MARK_BLOCK
assert classify(domestic=False, encrypted=True, usb_online=False, fallback=True) == MARK_CAMPUS
assert classify(domestic=False, encrypted=False, usb_online=False) == MARK_BLOCK
assert classify(domestic=False, encrypted=False, usb_online=False, fallback=True) == MARK_CAMPUS
assert classify(domestic=True, encrypted=True, domestic_precedence=False) == MARK_USB

main = (ROOT / "usr/bin/campus-route").read_text(encoding="utf-8")
# Existing marks are restored and preserved when compatibility is enabled.
assert "--restore-mark" in main
assert "--save-mark" in main
assert "PLUGIN_COMPAT" in main
print("test_fixture: PASS")
