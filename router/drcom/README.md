# Dr.COM 自动认证（路由器模板）

本目录是 QWRT/OpenWrt 的 Dr.COM 登录与保活 LuCI 包。默认关闭，配置文件中的 `PORTAL_HOST`、`CAMPUS_USERNAME`、`CAMPUS_PASSWORD` 只是占位符。

## 配置

```sh
uci set drcom.main.portal_host='PORTAL_HOST'
uci set drcom.main.username='CAMPUS_USERNAME'
uci set drcom.main.password='CAMPUS_PASSWORD'
uci set drcom.main.operator='free'
uci set drcom.main.user_suffix=''
uci set drcom.main.enabled='1'
uci commit drcom
chmod 600 /etc/config/drcom
/etc/init.d/drcom-auto-login enable
/etc/init.d/drcom-auto-login restart
```

### 运营商选择

LuCI 的“运营商”下拉框提供：免费校园网、中国移动、中国联通、中国电信、中国广电。
中国广电模板对应门户请求中的 `R3=4`、`R6=0`、`terminal_type=1`、`jsVersion=4.2.1`、`v=6780`。
移动、联通和电信在不同学校可能使用不同字段，选择后仍沿用可编辑的协议参数；如学校要求账号后缀，可填写 `user_suffix`，例如 `@telecom`。

服务会先访问状态接口，只有未在线时才发送登录 GET 请求；凭据不会写入日志。不同门户可能使用不同的路径、字段或回调值，请在本地浏览器开发者工具中确认后修改 UCI。

LuCI 页面：`服务 → Dr.COM 自动认证`。
