# Campus Route router deliverable

This directory is a staged QWRT/OpenWrt 21.02 router implementation. It does not
contain portal credentials or the live router's existing Dr.COM/DNS files.

## Behaviour

* enabled=0 is the shipped default. The service only removes objects that it
  created and leaves existing firewall/plugin rules intact.
* With the service enabled, 0x1000 marks domestic CIDR destinations for the
  campus logical interface (wan by default). 0x2000 marks overseas, unknown,
  TCP/TLS, UDP/QUIC, DoH/DoT-style ports for USB (wanusb, then wwan). 0x3000
  is a fail-closed mark.
* `campus_failover=1` (the default) continuously checks the campus uplink. If
  its default route disappears or all configured literal-IP probes fail,
  domestic traffic is temporarily marked 0x2000 so the entire router/LAN uses
  USB. Two consecutive successful probes restore domestic traffic to campus;
  the `campus_health_state` and reason are exposed by `campus-route status`.
  The daemon reconciles at `reconcile_interval` (30 seconds by default), so a
  scheduled campus cutoff around 23:30 is detected without a manual action.
* If USB has no device and no default route, USB-selected traffic is marked
  0x3000 and rejected in both IPv4 and IPv6 FORWARD/OUTPUT chains. Setting
  usb_missing_fallback=1 changes only this unavailable-USB path to campus.
* plugin_compat=1 preserves any pre-existing non-zero packet mark; when it is
  zero (the default), Campus Route classifies the packet and only changes the
  high-nibble policy bits (mark_mask=0xf000). Existing connmark values are
  restored before classification and saved on a decision.
* The optional connection-level accelerator is controlled by `accel_enabled=0`
  (default). When enabled, it measures campus throughput and domestic flow
  pressure. After the configured hysteresis window it assigns only *new*
  domestic TCP/UDP connections to USB with a 10% starting share, stepping up
  to the configured cap (50% by default). Existing connections retain their
  connmark and are never moved packet-by-packet. Campus/USB health failure,
  unsupported scope, or a missing `xt_statistic`/conntrack backend immediately
  drops the share to zero while leaving the base policy intact.
* Each policy table also contains the connected LAN prefixes (including
  `br-lan`). This is required because fwmark rules run before the main table;
  without the LAN route, marked replies to clients could be sent out a WAN
  default.
* The CN IPv4/IPv6 ipsets are atomically rebuilt from plain CIDR caches. A
  GeoSite text file is kept as metadata/degraded-state information; the data
  plane remains CIDR based so it cannot assume every connection used local DNS.

## Install on QWRT

Copy this directory to the router, inspect the template, then run as root:

    # optional dry run
    ./install.sh --dry-run
    # live install; policy remains disabled
    ./install.sh
    /etc/init.d/campus-route enable
    /etc/init.d/campus-route start
    # after verifying USB and campus interfaces
    uci set campus_route.main.enabled=1
    uci commit campus_route
    /etc/init.d/campus-route restart

Dependencies are checked before any policy write: iptables-legacy,
ip6tables-legacy (when IPv6 is enabled), ipset, ip, and uci. An iptables binary
with an nf_tables backend is rejected rather than mixed with legacy rules. The
implementation discovers l3 devices/gateways via ubus and jsonfilter, falling
back to the logical name when it is a kernel device.

On QWRT systems where the vendor `modemdata` service is enabled for `usb0`,
the installer disables that service when `wanusb` is the configured primary.
This prevents a second DHCP client and duplicate default route on the same USB
tether device; the `wwan` stanza remains available as an explicitly disabled
fallback.

## Commands and WebUI

    /usr/bin/campus-route status
    /usr/bin/campus-route-accel status
    /usr/bin/campus-route reconcile
    /usr/bin/campus-route refresh
    /usr/bin/campus-route snapshot [DIRECTORY]
    /usr/bin/campus-route-rollback [--dry-run] SNAPSHOT_DIRECTORY

The staged snapshot.sh and rollback.sh wrappers call those installed commands.

LuCI page: Services -> Campus Route. It exposes fixed status, apply, refresh,
start, and stop actions plus UCI fields for interfaces, IPv6, unknown policy,
encrypted TCP/UDP ports, USB fallback, campus health probes/failover,
plugin compatibility, connection-level acceleration thresholds, rule sources,
and routing table overrides. The status JSON includes campus Mbps, active
domestic-flow estimates, current USB share, moved-flow/byte counters, and the
last acceleration reason. No arbitrary shell RPC is exposed.

### Aggregation acceleration

The following defaults implement a conservative 500 Mbps campus cap:

```text
accel_enabled=0
bandwidth_cap_mbps=500
accel_trigger_percent=85
accel_release_percent=75
accel_min_active_flows=8
accel_min_new_flows_per_sec=2
accel_trigger_seconds=10
accel_release_seconds=30
accel_max_usb_share_percent=50
accel_step_percent=10
accel_sample_interval=5
```

The daemon samples counters every five seconds. A qualifying high-load window
must persist for ten seconds before 10% of subsequent domestic connections
are selected for USB. Further ten-second windows add 10 percentage points up
to the cap. Low load below 75% for 30 seconds removes one step at a time. The
selection uses `xt_statistic` on `ctstate NEW` packets with zero policy
mark/connmark; a private connmark bit identifies selected flows for byte
accounting. This is connection distribution, not packet bonding, so a TCP or
QUIC flow remains on its original outlet for its lifetime.

#### Hotspot learning for short bursts

测速常在几秒内突发大量并发连接，可能在固定触发窗口完成前就结束。开启
`accel_learning_enabled=1`（默认）后，采样器在校园网利用率达到
`accel_hot_trigger_percent` 且出现足够新连接时，从已标记为校园网的国内
活动连接中提取目的 IP，写入带 TTL 的 `campus_accel_hot4/6` 集合。后续同一
目的 IP 的**新建**国内连接会优先按当前加速比例走 USB；已建立连接、带有
策略 mark/connmark 的连接以及插件接管流量保持原路径。缓存只存于
`/var/run/campus-route`，默认 900 秒后过期，最多 256 条，不记录 URL、账号
或密码。LuCI 状态会显示缓存条目、学习次数、最近时间和原因。

Hotplug file etc/hotplug.d/iface/95-campus-route reconciles after ifup and
ifdown. etc/cron.d/campus-route refreshes lists weekly at 04:17; the installer
mirrors that line into /etc/crontabs/root without duplicating it.

## Rule sources and rollback

campus-route-update first looks for plain CN files generated by OpenClash or
Passwall. If no plugin cache is found it downloads the configured HTTPS URLs
using uclient-fetch, curl, or wget, validates CIDRs, optionally checks SHA-256,
and atomically replaces the cache. Download/parse/checksum failure keeps the
last-known-good file. insecure_fetch=1 is an explicit, visible
certificate-verification exception and is off by default. Version and license
metadata are retained in /etc/campus-route/rules.state for audit.

Before changes, run campus-route snapshot /etc/campus-route/snapshots/baseline.
Rollback stops this service, restores only campus_route.uci, reloads firewall3,
and starts the service only when the snapshot was enabled. It deliberately does
not restore full iptables-save output, which could overwrite unrelated
OpenClash/Passwall chains; snapshot files are retained for audit/verification.

## Static checks

On a development host without an OpenWrt kernel, run:

    python tests/test_static.py
    python tests/test_fixture.py

The checks verify default-off policy, fixed chain/set/mark names, IPv4+IPv6
coverage, USB fail-closed/fallback paths, plugin-compat behaviour, atomic rule
updates, LuCI fixed endpoints, and the rollback/install inventory. A live
router test should additionally inspect iptables-legacy -S, ip -4/-6 rule,
ipset list, and the JSON returned by campus-route status.
