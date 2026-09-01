# 配置参考

## 路由器 UCI

主要配置位于 `/etc/config/campus_route`。首次部署建议保持：

```text
enabled=0
usb_missing_action=reject
usb_missing_fallback=0
plugin_compat=0
campus_failover=1
ipv6=1
unknown_policy=usb
```

校园网每天在固定时段断线时，保持 `campus_failover=1`，并使用不依赖 DNS 的字面量探测地址。系统会在每个 `reconcile_interval`（默认 30 秒）执行健康探测；失败达到阈值后把校园网目标改为 USB，连续成功达到恢复阈值后再切回。

## 多线程下载/上传聚合加速

加速功能默认关闭，与基础分流相互独立。它只把**新建的国内数据连接**按比例分配到 USB，不会把已经建立的 TCP/QUIC 连接逐包迁移。校园网或 USB 任一方向没有可用默认路由、校园网健康探测失败、或固件缺少 `xt_statistic`/conntrack 统计能力时，加速自动降级为 0%，基础策略继续运行。

```text
option accel_enabled '0'
option bandwidth_cap_mbps '500'
option accel_trigger_percent '85'
option accel_release_percent '75'
option accel_min_active_flows '8'
option accel_min_new_flows_per_sec '2'
option accel_trigger_seconds '10'
option accel_release_seconds '30'
option accel_max_usb_share_percent '50'
option accel_step_percent '10'
option accel_sample_interval '5'
option accel_learning_enabled '1'
option accel_hot_ttl '900'
option accel_hot_max_entries '256'
option accel_hot_trigger_percent '60'
option accel_hot_min_new_flows '2'
```

以 500 Mbps 为例，校园网任一方向达到约 425 Mbps（85%）且同时满足活动连接数、新连接频率条件并持续 10 秒后，状态进入“加速中”，从 10% USB 分流开始。高负载每满足一个触发窗口增加一个步长，最高 50%；低于 75% 持续 30 秒则逐步释放。

状态文件位于 `/var/run/campus-route/accel.state` 与 `/var/run/campus-route/accel.stats`，LuCI 的状态 JSON 会显示速率、活动连接、新连接频率、当前分流比例、转移连接数/字节数和最近原因。加速采样器与主服务共用 reconcile 锁；策略更新仍只通过固定的 `status`、`apply`、`start`、`stop` 命令完成。

### 短时突发热点学习

测速或多线程下载持续时间较短时，可启用热点学习。采样器在达到
`accel_hot_trigger_percent`（默认 60%）并检测到 `accel_hot_min_new_flows`
（默认 2 条/秒）时，将当时校园网承载的国内目的 IP 加入临时热点集合。集合
使用 ipset TTL（默认 900 秒、最多 256 条）；下一次同一目的 IP 建立新连接时，
会在普通国内规则前优先进入 USB 分流。学习只影响后续新连接，不迁移既有
TCP/QUIC 连接，也不处理海外、私网、DNS/NTP 或插件已有 mark 的流量。IPv4
和 IPv6 使用独立集合，USB/校园网任一异常时自动停用。

## Windows 配置

Windows 的 `%ProgramData%\\CampusRoute\\config.json` 只保存策略、接口选择、门户 URL 和轮询间隔。账号与密码由 Credential Manager 管理，使用 GUI 的凭据设置，不要手工把秘密写入 JSON。

## 规则源

`campus-route-update` 优先读取 OpenClash/Passwall 生成的纯文本 CN 网段；否则从配置的 HTTPS 地址下载。下载、解析或校验失败时继续使用 last-known-good 缓存。
