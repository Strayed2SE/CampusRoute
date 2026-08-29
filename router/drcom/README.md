# Dr.COM 自动认证（路由器模板）

本目录是 QWRT/OpenWrt 的 Dr.COM 登录与保活 LuCI 包。默认关闭，配置文件中的 `PORTAL_HOST`、`CAMPUS_USERNAME`、`CAMPUS_PASSWORD` 只是占位符。

## 配置

```sh
uci set drcom.main.portal_host='PORTAL_HOST'
uci set drcom.main.username='CAMPUS_USERNAME'
uci set drcom.main.password='CAMPUS_PASSWORD'
uci set drcom.main.enabled='1'
uci commit drcom
chmod 600 /etc/config/drcom
/etc/init.d/drcom-auto-login enable
/etc/init.d/drcom-auto-login restart
```

服务会先访问状态接口，只有未在线时才发送登录 GET 请求；凭据不会写入日志。不同门户可能使用不同的路径、字段或回调值，请在本地浏览器开发者工具中确认后修改 UCI。

LuCI 页面：`服务 → Dr.COM 自动认证`。
