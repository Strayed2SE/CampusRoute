#!/bin/sh
# Install the router-side Campus Route files.  By default this is a staging
# install and leaves the policy disabled (enabled=0).

PATH=/usr/sbin:/usr/bin:/sbin:/bin
SELF_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd)"
ROOT="$DESTDIR"
[ -n "$ROOT" ] || ROOT=/
DRY=0
ENABLE=0
for arg in "$@"; do
	case "$arg" in --dry-run) DRY=1 ;; --enable) ENABLE=1 ;; --help|-h) printf '%s\n' "Usage: DESTDIR=/tmp/root $0 [--dry-run] [--enable]"; exit 0 ;; esac
done

if [ "$DRY" -eq 0 ] && [ "$ROOT" = / ] && [ -f /etc/config/campus_route ]; then
	# Preserve an existing deployment before replacing its template.  The
	# snapshot also captures firewall/ipset/ip-rule state for audit/rollback.
	STAMP="$(date -u '+%Y%m%dT%H%M%SZ' 2>/dev/null || date '+%Y%m%d%H%M%S')"
	mkdir -p /etc/campus-route/install-backups
	cp -p /etc/config/campus_route "/etc/campus-route/install-backups/campus_route.$STAMP.uci"
	[ -x /usr/bin/campus-route ] && /usr/bin/campus-route snapshot "/etc/campus-route/install-backups/$STAMP" >/dev/null 2>&1 || true
fi

FILES="etc/config/campus_route etc/init.d/campus-route etc/hotplug.d/iface/95-campus-route etc/hotplug.d/net/95-campus-usb etc/cron.d/campus-route snapshot.sh rollback.sh usr/bin/campus-route usr/bin/campus-route-accel usr/bin/campus-route-update usr/bin/campus-route-rollback usr/lib/lua/luci/controller/campus_route.lua usr/lib/lua/luci/model/cbi/campus_route/main.lua usr/share/rpcd/acl.d/luci-app-campus-route.json"
for rel in $FILES; do
	if [ "$DRY" -eq 1 ]; then printf 'copy %s -> %s\n' "$rel" "$ROOT/$rel"; continue; fi
	mkdir -p "$ROOT/$(dirname -- "$rel")" || exit 1
	cp -f "$SELF_DIR/$rel" "$ROOT/$rel" || exit 1
done
if [ "$DRY" -eq 0 ]; then
	mkdir -p "$ROOT/etc/campus-route/rules" "$ROOT/etc/campus-route/snapshots" || exit 1
	for rel in cn4.txt cn6.txt geosite-cn.txt; do
		[ -f "$ROOT/etc/campus-route/rules/$rel" ] || cp -f "$SELF_DIR/usr/share/campus-route/rules/$rel" "$ROOT/etc/campus-route/rules/$rel"
	done
	chmod 0600 "$ROOT/etc/config/campus_route" 2>/dev/null || true
	chmod 0755 "$ROOT/etc/init.d/campus-route" "$ROOT/etc/hotplug.d/iface/95-campus-route" "$ROOT/etc/hotplug.d/net/95-campus-usb" "$ROOT/snapshot.sh" "$ROOT/rollback.sh" "$ROOT/usr/bin/campus-route" "$ROOT/usr/bin/campus-route-accel" "$ROOT/usr/bin/campus-route-update" "$ROOT/usr/bin/campus-route-rollback"
	CRON="$ROOT/etc/crontabs/root"; mkdir -p "$(dirname -- "$CRON")"
	if [ ! -f "$CRON" ] || ! grep -q '/usr/bin/campus-route refresh' "$CRON" 2>/dev/null; then printf '%s\n' '17 4 * * 0 uci -q get campus_route.main.rule_refresh 2>/dev/null | grep -qx weekly && /usr/bin/campus-route refresh >/dev/null 2>&1' >> "$CRON"; fi
	if [ ! -f "$CRON" ] || ! grep -q '/usr/bin/campus-route reconcile' "$CRON" 2>/dev/null; then printf '%s\n' '* * * * * uci -q get campus_route.main.enabled 2>/dev/null | grep -qx 1 && /usr/bin/campus-route reconcile >/dev/null 2>&1' >> "$CRON"; fi
	# QWRT's optional modemdata service can claim the same usb0 device and
	# start a second DHCP client.  When the configured primary is wanusb, keep
	# modemdata disabled so Campus Route remains the sole USB uplink owner.
	if [ "$ROOT" = / ] && [ -f /etc/config/modemdata ] && [ "$(uci -q get campus_route.main.usb_iface_primary 2>/dev/null)" = wanusb ]; then
		uci -q set modemdata.@service[0].enabled=0
		uci -q commit modemdata
		/etc/init.d/modemdata disable >/dev/null 2>&1 || true
		ubus call network.interface.wwan down >/dev/null 2>&1 || true
		ubus call network.interface.wwan6 down >/dev/null 2>&1 || true
	fi
fi
if [ "$ENABLE" -eq 1 ]; then
	[ "$ROOT" = / ] || { printf '%s\n' '--enable requires a live target (DESTDIR=/)' >&2; exit 2; }
	/etc/init.d/campus-route enable
	/etc/init.d/campus-route start
fi
printf '%s\n' "Campus Route files installed under $ROOT; policy remains disabled until enabled=1 is committed."
