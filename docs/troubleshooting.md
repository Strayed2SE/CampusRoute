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

## 加速显示“降级”或始终为“监测中”

执行：

```sh
/usr/bin/campus-route status
/usr/bin/campus-route-accel status
iptables-legacy -t mangle -S CAMPUS_ROUTE_ACCEL_SELECT
iptables-legacy -t mangle -S CAMPUS_ROUTE_ACCEL_MOVED
```

`accel_reason=backend_unavailable` 表示固件缺少 `xt_statistic`、`xt_conntrack` 或 conntrack 表；此时基础国内/海外分流不受影响。`link_unavailable` 表示校园网或 USB 没有默认路由，先恢复对应接口。`threshold_not_met` 表示带宽、活动连接数或新连接频率尚未同时达到阈值。

加速只作用于新建国内连接。下载已经开始后 USB 分流比例变化不会重置连接；观察 `moved_flows` 和 `moved_bytes` 可确认后续连接是否被选中。若启用了 OpenClash/Passwall 兼容，已有非零 mark 会在加速选择之前返回，不会被接管。


## 短时测速未触发加速

如果测速很短、状态一直是“监测中”，可检查热点学习字段：

```sh
/usr/bin/campus-route-accel status
ipset list campus_accel_hot4
ipset list campus_accel_hot6
```

`hot_count4/6` 表示当前缓存条目，`hot_learned` 是累计学习次数，
`hot_last_reason=pretrigger` 表示在常规触发窗口完成前捕获了突发负载。缓存
只保存目的 IP，自动按 `accel_hot_ttl` 过期；清空缓存可执行 `campus-route
reconcile force`（会重建基础集合与策略）。若没有 conntrack 表或 `ipset`
不支持 timeout，热点学习保持关闭，基础分流继续运行。
