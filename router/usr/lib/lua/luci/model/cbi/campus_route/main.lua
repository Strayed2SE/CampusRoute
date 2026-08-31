local sys = require "luci.sys"

m = Map("campus_route", translate("Campus Route"), translate("双出口策略路由：国内目的地优先走校园网，海外/未知/加密流量走 USB；USB 缺失时默认阻断。首次部署保持关闭。"))

s = m:section(NamedSection, "main", "campus_route", translate("主策略"))
s.anonymous = true
s.addremove = false

o = s:option(Flag, "enabled", translate("启用主策略"))
o.rmempty = false
o.default = "0"
o.description = translate("确认 USB 接口在线后再启用；关闭时不改变现有网络行为。")

o = s:option(Value, "campus_iface", translate("校园网接口"))
o.default = "wan"
o.rmempty = false
o.description = translate("填写 UCI 逻辑接口名称，例如 wan。")

o = s:option(Value, "usb_iface_primary", translate("USB 主接口"))
o.default = "wanusb"
o.rmempty = false

o = s:option(Value, "usb_iface_fallback", translate("USB 兼容接口"))
o.default = "wwan"
o.rmempty = false

o = s:option(ListValue, "usb_missing_action", translate("USB 缺失动作"))
o:value("reject", translate("阻断（推荐）"))
o:value("fallback", translate("按回退开关处理"))
o.default = "reject"
o.rmempty = false

o = s:option(Flag, "usb_missing_fallback", translate("USB 缺失时回退校园网"))
o.default = "0"
o.rmempty = false
o.description = translate("默认关闭；开启后仅在 USB 无在线网关时将原本选择 USB 的流量送往校园网。")

o = s:option(Flag, "campus_failover", translate("校园网不可用时切换 USB"))
o.default = "1"
o.rmempty = false
o.description = translate("校园网接口掉线或健康探测失败时，国内、海外和未知流量统一切换到 USB；恢复后自动恢复国内走校园网。")

o = s:option(Flag, "campus_healthcheck", translate("启用校园网健康探测"))
o.default = "1"
o.rmempty = false
o.description = translate("使用下方 IP 地址通过校园网探测；关闭后仅依据接口默认路由判断。")

o = s:option(DynamicList, "campus_probe_host", translate("校园网探测地址"))
o.datatype = "ipaddr"
o:value("223.5.5.5")
o:value("180.76.76.76")
o.default = "223.5.5.5"
o.rmempty = false
o.description = translate("填写可由校园网访问的 IPv4/IPv6 地址，不要填写域名，以免 DNS 影响探测。")

o = s:option(Value, "campus_probe_timeout", translate("探测超时（秒）"))
o.datatype = "and(uinteger,min(1),max(15))"
o.default = "2"
o.rmempty = false

o = s:option(Value, "campus_fail_threshold", translate("切换失败次数"))
o.datatype = "and(uinteger,min(1),max(10))"
o.default = "1"
o.rmempty = false
o.description = translate("连续失败达到次数后切换到 USB；默认一次失败即可切换。")

o = s:option(Value, "campus_recover_threshold", translate("恢复成功次数"))
o.datatype = "and(uinteger,min(1),max(10))"
o.default = "2"
o.rmempty = false
o.description = translate("连续成功达到次数后恢复国内流量走校园网，避免 23:30 附近链路抖动。")

o = s:option(Flag, "plugin_compat", translate("OpenClash/Passwall 兼容"))
o.default = "0"
o.rmempty = false
o.description = translate("默认关闭；开启后只处理没有已有 mark/connmark 的流量。")

o = s:option(Flag, "ipv6", translate("启用 IPv6 分流"))
o.default = "1"
o.rmempty = false

o = s:option(Flag, "accel_enabled", translate("多线程聚合加速"))
o.default = "0"
o.rmempty = false
o.description = translate("默认关闭；仅在校园网和 USB 都在线、国内连接持续高负载时，将新建国内连接的一部分分配到 USB。")

o = s:option(DummyValue, "_accel_advanced", translate("高级加速设置"))
o.rawhtml = true
o.default = translate("展开“多线程聚合加速”后调整阈值；关闭加速时这些参数不会安装任何规则。")

o = s:option(Value, "bandwidth_cap_mbps", translate("宽带封顶速度（Mbps）"))
o.datatype = "and(uinteger,min(1),max(100000))"
o.default = "500"
o.rmempty = false
o.description = translate("填写校园网单方向封顶速度，例如 500。")

o = s:option(Value, "accel_trigger_percent", translate("加速触发利用率（%）"))
o.datatype = "and(uinteger,min(50),max(99))"
o.default = "85"
o.rmempty = false
o:depends("accel_enabled", "1")

o = s:option(Value, "accel_release_percent", translate("加速释放利用率（%）"))
o.datatype = "and(uinteger,min(1),max(98))"
o.default = "75"
o.rmempty = false
o:depends("accel_enabled", "1")

o = s:option(Value, "accel_min_active_flows", translate("最少活动连接数"))
o.datatype = "and(uinteger,min(2),max(100000))"
o.default = "8"
o.rmempty = false
o:depends("accel_enabled", "1")

o = s:option(Value, "accel_min_new_flows_per_sec", translate("最少新连接频率（条/秒）"))
o.datatype = "and(uinteger,min(1),max(10000))"
o.default = "2"
o.rmempty = false
o:depends("accel_enabled", "1")

o = s:option(Value, "accel_trigger_seconds", translate("触发持续时间（秒）"))
o.datatype = "and(uinteger,min(5),max(3600))"
o.default = "10"
o.rmempty = false
o:depends("accel_enabled", "1")

o = s:option(Value, "accel_release_seconds", translate("释放持续时间（秒）"))
o.datatype = "and(uinteger,min(10),max(3600))"
o.default = "30"
o.rmempty = false
o:depends("accel_enabled", "1")

o = s:option(Value, "accel_max_usb_share_percent", translate("最大 USB 分流比例（%）"))
o.datatype = "and(uinteger,min(10),max(80))"
o.default = "50"
o.rmempty = false
o:depends("accel_enabled", "1")

o = s:option(Value, "accel_step_percent", translate("每次增加分流比例（%）"))
o.datatype = "and(uinteger,min(1),max(80))"
o.default = "10"
o.rmempty = false
o:depends("accel_enabled", "1")

o = s:option(Value, "accel_sample_interval", translate("加速采样间隔（秒）"))
o.datatype = "and(uinteger,min(2),max(30))"
o.default = "5"
o.rmempty = false
o:depends("accel_enabled", "1")

o = s:option(ListValue, "unknown_policy", translate("未知目的地"))
o:value("usb", translate("USB"))
o:value("campus", translate("校园网"))
o:value("reject", translate("阻断"))
o.default = "usb"
o.rmempty = false

o = s:option(Flag, "domestic_precedence", translate("国内优先于加密端口"))
o.default = "1"
o.rmempty = false

o = s:option(DynamicList, "encrypted_tcp", translate("加密 TCP 端口"))
o.datatype = "port"
o:value("443")
o:value("853")
o:value("8443")
o.default = "443"

o = s:option(DynamicList, "encrypted_udp", translate("加密 UDP/QUIC 端口"))
o.datatype = "port"
o:value("443")
o:value("784")
o:value("8853")
o.default = "443"

o = s:option(ListValue, "rule_refresh", translate("规则刷新"))
o:value("weekly", translate("每周低峰"))
o:value("manual", translate("仅手动"))
o.default = "weekly"
o.rmempty = false

o = s:option(ListValue, "scope", translate("策略作用域"))
o:value("router_only", translate("仅路由器本机"))
o:value("lan_only", translate("仅 LAN 转发"))
o:value("router_and_lan", translate("路由器 + LAN"))
o.default = "router_and_lan"
o.rmempty = false

o = s:option(DummyValue, "_status", translate("运行状态"))
function o.cfgvalue(self, section)
	local out = sys.exec("/usr/bin/campus-route status 2>/dev/null")
	return (out and out:gsub("%s+$", "")) or ""
end

o = s:option(Button, "_apply", translate("应用策略"))
o.inputstyle = "apply"
o.write = function()
	sys.call("/usr/bin/campus-route reconcile >/dev/null 2>&1")
	end

o = s:option(Button, "_refresh", translate("刷新规则"))
o.inputstyle = "apply"
o.write = function()
	sys.call("/usr/bin/campus-route refresh >/dev/null 2>&1")
	end

o = s:option(Button, "_start", translate("启动服务"))
o.inputstyle = "apply"
o.write = function()
	sys.call("/etc/init.d/campus-route start >/dev/null 2>&1")
	end

o = s:option(Button, "_stop", translate("停止服务"))
o.inputstyle = "reset"
o.write = function()
	sys.call("/etc/init.d/campus-route stop >/dev/null 2>&1")
	end

o = s:option(Value, "cn4_file", translate("IPv4 CIDR 缓存"))
o.default = "/etc/campus-route/rules/cn4.txt"
o.rmempty = false
o = s:option(Value, "cn6_file", translate("IPv6 CIDR 缓存"))
o.default = "/etc/campus-route/rules/cn6.txt"
o.rmempty = false
o = s:option(Value, "geosite_file", translate("GeoSite 域名缓存"))
o.default = "/etc/campus-route/rules/geosite-cn.txt"
o.rmempty = false
o = s:option(Value, "cn4_source", translate("IPv4 更新地址"))
o.placeholder = "https://..."
o = s:option(Value, "cn6_source", translate("IPv6 更新地址"))
o.placeholder = "https://..."
o = s:option(Value, "geosite_source", translate("GeoSite 更新地址"))
o.placeholder = translate("留空则自动读取插件缓存")
o = s:option(Value, "update_timeout", translate("更新超时（秒）"))
o.datatype = "and(uinteger,min(5),max(120))"
o.default = "30"
o.rmempty = false
o = s:option(Flag, "insecure_fetch", translate("跳过更新证书校验"))
o.default = "0"
o.description = translate("默认关闭，仅用于无可用 CA 链的临时网络。")
o = s:option(Value, "maxelem", translate("ipset 最大条目"))
o.datatype = "and(uinteger,min(1024),max(1000000))"
o.default = "200000"
o.rmempty = false
o = s:option(Value, "mark_mask", translate("策略 mark 掩码"))
o.default = "0xf000"
o.rmempty = false
o = s:option(Value, "campus_table", translate("校园网路由表（0=自动）"))
o.datatype = "uinteger"
o.default = "0"
o = s:option(Value, "usb_table", translate("USB 路由表（0=自动）"))
o.datatype = "uinteger"
o.default = "0"
o = s:option(Value, "block_table", translate("阻断路由表（0=自动）"))
o.datatype = "uinteger"
o.default = "0"

o = s:option(Value, "cn4_version", translate("IPv4 规则版本"))
o.default = "unversioned"
o = s:option(Value, "cn6_version", translate("IPv6 规则版本"))
o.default = "unversioned"
o = s:option(Value, "geosite_version", translate("GeoSite 版本"))
o.default = "unversioned"
o = s:option(Value, "rules_license", translate("规则许可证/来源说明"))
o.placeholder = translate("按数据源要求填写")

function m.on_after_commit(self)
	sys.call("/usr/bin/campus-route reconcile >/dev/null 2>&1")
end

return m
