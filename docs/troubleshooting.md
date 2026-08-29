# 故障排查

## 局域网间歇断网

确认每个策略路由表都包含 LAN 的 connected route，并检查：

```sh
ip -4 rule
ip -4 route show table all
iptables-legacy -t mangle -S CAMPUS_ROUTE_MANGLE
iptables-legacy -t filter -S CAMPUS_ROUTE_FILTER
```

不要同时让多个服务为同一 USB 设备运行 DHCP 客户端；QWRT 上应关闭重复的 USB 接管服务。

## `DNS_PROBE_FINISHED_NO_INTERNET`

先执行 `/usr/bin/campus-route status`。如果 `usb_online4=0` 且主策略选择 USB，默认阻断是预期行为；插入并重新获取 USB 默认路由后执行 `campus-route reconcile`。如果校园网在断线时应允许全部流量回退，才开启 `usb_missing_fallback=1`。

## LuCI 页面 500

清理 LuCI 缓存并重启 uhttpd：

```sh
rm -f /tmp/luci-indexcache /tmp/luci-modulecache
/etc/init.d/uhttpd restart
```

控制器只使用固定入口，不支持任意 shell RPC。
