#!/usr/bin/env python3
"""Regression checks for signature-driven, incremental reconciliation."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "usr/bin/campus-route").read_text(encoding="utf-8")


def decide(*, saved_data, current_data, plane_present,
           saved_policy, current_policy, force=False):
    """Mirror reconcile's high-level cache decision without system commands."""
    if force or not saved_data or saved_data != current_data or not plane_present:
        return "full"
    if not saved_policy or saved_policy != current_policy:
        return "policy"
    return "health"


# First install is full; repeated identical checks are health-only.
assert decide(saved_data="", current_data="A", plane_present=False,
              saved_policy="", current_policy="P") == "full"
assert decide(saved_data="A", current_data="A", plane_present=True,
              saved_policy="P", current_policy="P") == "health"
assert decide(saved_data="A", current_data="A", plane_present=True,
              saved_policy="P", current_policy="P") == "health"

# Effective target changes update only chains. Config/interface/rule changes or
# externally removed data-plane objects trigger one complete repair.
assert decide(saved_data="A", current_data="A", plane_present=True,
              saved_policy="P", current_policy="Q") == "policy"
assert decide(saved_data="A", current_data="B", plane_present=True,
              saved_policy="P", current_policy="P") == "full"
assert decide(saved_data="A", current_data="A", plane_present=False,
              saved_policy="P", current_policy="P") == "full"
assert decide(saved_data="A", current_data="A", plane_present=True,
              saved_policy="P", current_policy="P", force=True) == "full"

# IPv6 RA defaults commonly contain a decreasing `expires` value. It must not
# make an otherwise unchanged interface look different every health interval.
def normalize_route(line):
    return re.sub(r"\s+(?:expires|age)\s+\S+", "", line)


ra_a = "default via fe80::1 dev usb0 proto ra metric 512 expires 1799sec pref medium"
ra_b = "default via fe80::1 dev usb0 proto ra metric 512 expires 1769sec pref medium"
assert normalize_route(ra_a) == normalize_route(ra_b)

# Structural linkage: expensive installers live only in the full branch. The
# steady branch probes health and conditionally updates only firewall policy.
reconcile_start = SCRIPT.index("\nreconcile() {")
reconcile_end = SCRIPT.index("\nteardown()", reconcile_start)
reconcile = SCRIPT[reconcile_start:reconcile_end]
steady_marker = "\telse\n\t\t# Steady state: perform only the health probe."
assert steady_marker in reconcile
full_branch, steady_branch = reconcile.split(steady_marker, 1)
for heavy in ('setup_routes ||', 'setup_rules ||', 'ensure_ipset "$SET4"'):
    assert heavy in full_branch, heavy
    assert heavy not in steady_branch, heavy
assert "if setup_geosite; then" in full_branch
assert '[ -f "$GEOSITE_RETRY_FILE" ]' in steady_branch
assert "update_campus_health" in steady_branch
assert '[ "$old_policy" != "$POLICY_SIGNATURE" ]' in steady_branch
assert "setup_firewall ||" in steady_branch

# Data signatures include UCI, interfaces/routes, chosen tables and rule-file
# fingerprints, but not health counters. Policy signatures include only values
# capable of changing effective targets plus the one-tick reclassify flag.
data_start = SCRIPT.index("\nbuild_data_signature()")
policy_start = SCRIPT.index("\nbuild_policy_signature()", data_start)
probe_start = SCRIPT.index("\n# Probe one literal IP", policy_start)
data_sig = SCRIPT[data_start:policy_start]
policy_sig = SCRIPT[policy_start:probe_start]
for token in ("uci -q show", "CAMPUS_ROUTE4", "USB_ROUTE4", "CAMPUS_TABLE",
              "file_fingerprint", "route_fingerprint"):
    assert token in data_sig, token
assert "expires" in SCRIPT[SCRIPT.index("\nroute_fingerprint()") : data_start]
for token in ("CAMPUS_ONLINE", "USB_ONLINE4", "USB_ONLINE6",
              "FORCE_RECLASSIFY"):
    assert token in policy_sig, token
for token in ("CAMPUS_HEALTH_FAILURES", "CAMPUS_HEALTH_SUCCESSES"):
    assert token not in data_sig and token not in policy_sig, token

# Disabled daemon state is cleaned once per transition instead of repeatedly.
daemon_start = SCRIPT.index("\ndaemon_loop()")
daemon_end = SCRIPT.index("\nsnapshot()", daemon_start)
daemon = SCRIPT[daemon_start:daemon_end]
assert 'last_enabled=unknown' in daemon
assert '[ "$last_enabled" != 0 ]' in daemon

# Teardown shares the reconcile lock and release_lock verifies ownership. This
# prevents procd stop/reload or a stale worker from deleting a newer owner's
# lock while it is flushing policy state.
assert 'acquire_lock || return 0' in SCRIPT[SCRIPT.index('\nteardown()'):SCRIPT.index('\nstatus()', SCRIPT.index('\nteardown()'))]
assert '[ "$(cat "$LOCK_DIR/pid" 2>/dev/null)" = "$$" ] || return 0' in SCRIPT

# Every fwmark-selected table must retain the connected LAN route; otherwise
# marked replies to clients are sent to a WAN default instead of br-lan.
for token in ('CAMPUS_LAN_DEV',
              'populate_lan_table 4 "$CAMPUS_LAN_DEV" "$CAMPUS_TABLE"',
              'populate_lan_table 4 "$CAMPUS_LAN_DEV" "$USB_TABLE"',
              'populate_lan_table 4 "$CAMPUS_LAN_DEV" "$BLOCK_TABLE"',
              'table_has_lan_route 4 "$CAMPUS_TABLE"',
              'table_has_lan_route 4 "$USB_TABLE"',
              'table_has_lan_route 4 "$BLOCK_TABLE"'):
    assert token in SCRIPT, token

# A failed/contended iptables mutation must not be accepted as a successful
# policy update. setup_firewall validates both chain content and hook linkage
# before reconcile writes the policy signature.
firewall_start = SCRIPT.index('\nsetup_firewall()')
firewall_end = SCRIPT.index('\nfamily_firewall_present()', firewall_start)
firewall = SCRIPT[firewall_start:firewall_end]
assert 'family_firewall_present "$IPT4" || return 1' in firewall
assert "grep -q -- '--restore-mark'" in SCRIPT
assert "grep -q -- 'MARK --set-xmark'" in SCRIPT

print("test_incremental: PASS")
