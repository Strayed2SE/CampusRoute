# CampusRoute

CampusRoute 是面向 QWRT/OpenWrt 与 Windows 10/11 x64 的双出口策略路由与校园网认证工具。它把国内目的地优先送往校园网，把海外、未知及常见加密流量送往 USB 网络共享；USB 不可用时默认阻断，避免流量意外回落到校园网。

> **适配说明**：项目中的 Dr.COM 登录参数来自一个特定高校门户的请求格式，当前更适合作为该类页面的模板。不同学校的域名、路径、字段或加密方式可能不同，需要在本地抓包后调整配置。仓库不包含任何真实账号、密码、令牌、管理地址或现场快照。

## 功能概览

- QWRT/OpenWrt：IPv4/IPv6、ipset、iptables-legacy、`ip rule` 多表策略路由。
- 校园网健康探测与自动故障切换；适合每天固定时段的校园网断线，检测到校园网不可用时自动切到 USB。
- USB 缺失默认 `REJECT`；可选的“回退校园网”开关默认关闭。
- OpenClash/Passwall 兼容开关默认关闭；开启后保留已有 mark/connmark。
- LuCI 页面 `服务 → Campus Route`，只暴露 status/apply/refresh/start/stop 固定 RPC。
- Dr.COM 自动认证与保活，凭据仅保存在路由器 UCI 配置或 Windows Credential Manager 中。
- Windows 单文件 x64 EXE、服务、托盘 GUI、WinDivert 驱动、快照与回滚脚本；只管理本机流量，不启用 ICS/桥接/LAN 转发。

## 默认策略

| 项目 | 默认值 |
| --- | --- |
| 路由器主开关 | 关闭 (`enabled=0`) |
| 国内目的地 | 校园网 |
| 海外/未知/加密端口 | USB |
| USB 不可用 | 阻断 (`REJECT`) |
| USB 缺失回退校园网 | 关闭 |
| OpenClash/Passwall 兼容 | 关闭 |
| IPv6 | 开启（若上行没有 IPv6 默认路由，可关闭） |
| 校园网故障切换 | 开启 |

## 快速上手：QWRT/OpenWrt

1. 将 `router/` 目录复制到路由器，先执行 `./install.sh --dry-run`，确认依赖与接口名称。
2. 执行 `./install.sh`。安装后服务仍保持关闭。
3. 如需 Dr.COM 保活，编辑 `/etc/config/drcom`，将以下占位符替换为本地值：

   ```sh
   uci set drcom.main.portal_host='PORTAL_HOST'
   uci set drcom.main.username='CAMPUS_USERNAME'
   uci set drcom.main.password='CAMPUS_PASSWORD'
   uci set drcom.main.enabled='1'
   uci commit drcom
   /etc/init.d/drcom-auto-login enable
   /etc/init.d/drcom-auto-login restart
   ```

   建议将配置权限设为 `0600`，不要把替换后的文件提交到 Git。
4. 确认 `campus_iface`、`usb_iface_primary`（通常为 `wanusb`）和 `usb_iface_fallback`（通常为 `wwan`）。
5. 确认 USB 已获得默认路由后，在 LuCI 的 Campus Route 页面应用并启动；或执行：

   ```sh
   uci set campus_route.main.enabled='1'
   uci commit campus_route
   /etc/init.d/campus-route restart
   /usr/bin/campus-route status
   ```

6. 使用 `campus-route status` 观察 `campus_health_state`、`usb_online4/6`、`last_error` 和命中计数。校园网健康探测失败时，国内流量会随下一次 reconcile 自动切换到 USB；恢复后连续成功探测再恢复国内走校园网。

### 回滚

```sh
/usr/bin/campus-route snapshot /etc/campus-route/snapshots/baseline
/usr/bin/campus-route-rollback --dry-run /etc/campus-route/snapshots/baseline
/usr/bin/campus-route-rollback /etc/campus-route/snapshots/baseline
```

## 快速上手：Windows

1. 从 GitHub Release 下载 Windows 包，或使用 `windows/build.ps1` 构建。
2. 以管理员身份运行 `install.ps1`。安装器会创建延迟自动启动服务、登录启动托盘任务、禁用状态的故障保护防火墙规则，并保存网络快照。
3. 在托盘 GUI 中选择校园网与 USB 网卡，填写门户地址和策略。Dr.COM 用户名/密码写入 Windows Credential Manager，不会写进 `config.json`、命令行或普通日志。
4. USB 断开时海外/未知/加密流量默认阻断；启用回退开关后才会明确回到校园网。
5. 卸载或回滚：

   ```powershell
   .\rollback.ps1
   .\uninstall.ps1
   ```

## 目录结构

```text
router/                  QWRT/OpenWrt Campus Route 与 Dr.COM LuCI 包
windows/                 Windows 服务、托盘 GUI、安装脚本、测试与驱动
docs/                    配置、故障排查与发布说明
scripts/                 本地测试/打包辅助脚本
artifacts/               可选的公开构建产物（不含现场配置）
```

## 测试与构建

```powershell
python router/tests/test_static.py
python router/tests/test_fixture.py
python router/tests/test_failover.py
python router/tests/test_incremental.py
python -m unittest discover -s windows/tests -v
python -m py_compile windows/campusroute.py
powershell -ExecutionPolicy Bypass -File windows/build.ps1
```

路由器脚本依赖 `iptables-legacy`、`ip6tables-legacy`（启用 IPv6 时）、`ipset`、`ip` 和 `uci`。更新规则时会先下载到临时文件、校验并原子替换；失败时保留上一版缓存。

## 安全与隐私

- 真实凭据只在目标设备本地配置；示例使用 `CAMPUS_USERNAME`、`CAMPUS_PASSWORD`、`PORTAL_HOST` 等占位符。
- 不要提交 `/etc/config/drcom`、Windows Credential Manager 导出、现场日志、网络快照、回滚目录或包含真实 IP/账号的抓包。
- 公开版默认关闭主策略、USB 回退和插件兼容；部署前先做快照并保留管理通道。
- 项目不绕过认证，不同步不同设备的凭据，也不启用 LAN 共享转发之外的系统代理功能。

## 已知限制

- Dr.COM 是厂商/学校定制协议；门户字段、状态接口和终端参数可能需要适配。
- 路由器数据面要求 legacy iptables；nftables-only 固件需要另行移植。
- USB 接口按可用默认路由选择；极少数同时存在 IPv4-only 与 IPv6-only USB 设备的环境需要拆分接口配置。
- Windows 驱动安装受驱动签名、Secure Boot/HVCI 和系统策略影响。

## 许可证

CampusRoute 自有代码采用 MIT，第三方 WinDivert 文件按其随附许可证发布，详见 `THIRD_PARTY_NOTICES.md`。
