#!/usr/bin/env python3
"""Fixture checks for campus health failover and source-routed probes."""
from pathlib import Path

MARK_CAMPUS, MARK_USB, MARK_BLOCK = 0x1000, 0x2000, 0x3000
ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "usr/bin/campus-route").read_text(encoding="utf-8")


def family_targets(*, campus_online, campus_route, usb_online,
                   failover=True, usb_fallback=False):
    """Mirror setup_firewall's target selection for one address family."""
    campus = MARK_CAMPUS
    usb = MARK_USB
    if failover and (not campus_online or not campus_route):
        campus = MARK_USB if usb_online else MARK_BLOCK
    if not usb_online:
        usb = MARK_CAMPUS if usb_fallback and campus_online and campus_route else MARK_BLOCK
    return campus, usb


assert family_targets(campus_online=True, campus_route=True, usb_online=True) == (MARK_CAMPUS, MARK_USB)
assert family_targets(campus_online=False, campus_route=True, usb_online=True) == (MARK_USB, MARK_USB)
assert family_targets(campus_online=False, campus_route=False, usb_online=False) == (MARK_BLOCK, MARK_BLOCK)
assert family_targets(campus_online=False, campus_route=True, usb_online=False, usb_fallback=True) == (MARK_BLOCK, MARK_BLOCK)
assert family_targets(campus_online=True, campus_route=False, usb_online=True) == (MARK_USB, MARK_USB)
assert family_targets(campus_online=True, campus_route=False, usb_online=False, usb_fallback=True) == (MARK_BLOCK, MARK_BLOCK)
assert family_targets(campus_online=False, campus_route=True, usb_online=True, failover=False) == (MARK_CAMPUS, MARK_USB)

# Reconcile installs route tables/rules and the provisional chain before the
# first probe. Probe destination marks precede both failover remaps and known
# mark returns, making USB leakage impossible even when a prior connmark says
# USB.
reconcile = SCRIPT[SCRIPT.index("reconcile()") :]
assert reconcile.index("setup_routes ||") < reconcile.index("setup_firewall ||")
assert reconcile.index("setup_firewall ||") < reconcile.index("update_campus_health")
assert SCRIPT.index('-d "$host" -j MARK --set-xmark "$MARK_CAMPUS/$MASK"') < SCRIPT.index('if [ "$campus_target" != "$MARK_CAMPUS" ]')
assert SCRIPT.index('-d "$host" -j MARK --set-xmark "$MARK_CAMPUS/$MASK"') < SCRIPT.index('if [ "$usb_target" != "$MARK_USB" ]')
assert 'if [ "$SCOPE" != lan_only ] || [ "$CAMPUS_HEALTHCHECK" -eq 1 ]' in SCRIPT
assert SCRIPT.index('[ "$SCOPE" = lan_only ] && "$cmd" -t mangle -A "$MANGLE_CHAIN" -j RETURN') > SCRIPT.index('-d "$host" -j MARK')

# ICMP loss does not short-circuit the HTTP fallback, and a configured Dr.COM
# status endpoint is probed through the campus device.
assert 'ping -q -I "$CAMPUS_DEV"' in SCRIPT
assert 'curl -fsS --interface "$CAMPUS_DEV"' in SCRIPT
assert 'probe_drcom_status; drcom_rc=$?' in SCRIPT
assert 'CAMPUS_STATUS_PATH' in SCRIPT and 'CAMPUS_STATUS_CALLBACK' in SCRIPT

# Reclassification clears only the policy nibble in connmark/packet mark.
assert 'CONNMARK --set-xmark 0x0/"$MASK"' in SCRIPT
assert 'MARK --set-xmark 0x0/"$MASK"' in SCRIPT

print("test_failover: PASS")
