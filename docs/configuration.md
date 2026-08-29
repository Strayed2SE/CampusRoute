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

## Windows 配置

Windows 的 `%ProgramData%\\CampusRoute\\config.json` 只保存策略、接口选择、门户 URL 和轮询间隔。账号与密码由 Credential Manager 管理，使用 GUI 的凭据设置，不要手工把秘密写入 JSON。

## 规则源

`campus-route-update` 优先读取 OpenClash/Passwall 生成的纯文本 CN 网段；否则从配置的 HTTPS 地址下载。下载、解析或校验失败时继续使用 last-known-good 缓存。
