local sys = require "luci.sys"

m = Map("drcom", translate("Dr.COM 自动认证"), translate("检测校园网认证状态；掉线时自动调用 Dr.COM 登录接口。"))

s = m:section(TypedSection, "drcom", translate("认证设置"))
s.anonymous = true
s.addremove = false

o = s:option(Flag, "enabled", translate("启用自动认证"))
o.rmempty = false
o.default = true

o = s:option(DummyValue, "_status", translate("当前状态"))
function o.cfgvalue(self, section)
	return sys.exec("/usr/bin/drcom-auto-login --status 2>/dev/null")
end

o = s:option(Button, "_login", translate("立即登录"), translate("先查询 /drcom/chkstatus；只有未登录时才发送登录请求。"))
o.inputstyle = "apply"
o.write = function()
	sys.call("/usr/bin/drcom-auto-login --once >/dev/null 2>&1")
end

o = s:option(Button, "_restart", translate("重启守护进程"))
o.inputstyle = "reload"
o.write = function()
	sys.call("/etc/init.d/drcom-auto-login restart >/dev/null 2>&1")
end

o = s:option(Value, "portal_host", translate("认证服务器"))
o.datatype = "host"
o.default = "PORTAL_HOST"
o.rmempty = false

o = s:option(Value, "login_path", translate("登录路径"))
o.default = "/drcom/login"
o.rmempty = false

o = s:option(ListValue, "operator", translate("运营商"), translate("免费校园网和四大运营商使用不同门户模板；中国广电已按 R3=4、R6=0、terminal_type=1、v=6780 适配。移动/联通/电信保留可编辑协议参数。"))
o:value("free", translate("免费校园网"))
o:value("china_mobile", translate("中国移动"))
o:value("china_unicom", translate("中国联通"))
o:value("china_telecom", translate("中国电信"))
o:value("china_broadnet", translate("中国广电"))
o.default = "free"
o.rmempty = false

o = s:option(Value, "status_path", translate("状态路径"))
o.default = "/drcom/chkstatus"
o.rmempty = false

o = s:option(Value, "username", translate("上网账号"))
o.rmempty = false

o = s:option(Value, "password", translate("上网密码"))
o.password = true
o.rmempty = false

o = s:option(Value, "user_suffix", translate("账号后缀"), translate("部分校园网要求在账号后追加运营商标识；默认留空，不自动猜测。"))
o.placeholder = "例如：@telecom"
o.rmempty = true

o = s:option(Value, "interval", translate("检测间隔（秒）"))
o.datatype = "and(uinteger,min(15),max(3600))"
o.default = "60"
o.rmempty = false

o = s:option(Value, "timeout", translate("请求超时（秒）"))
o.datatype = "and(uinteger,min(3),max(60))"
o.default = "10"
o.rmempty = false

o = s:option(Value, "iface", translate("WAN 接口"))
o.default = "wan"
o.rmempty = false

s = m:section(SimpleSection)
s.title = translate("协议参数")
s.description = translate("已按当前门户请求保留 callback、0MKKey、R1/R2/R3/R6、para、terminal_type、jsVersion、v 等字段；密码仅保存在 UCI 配置中，不写入日志。")

function m.on_after_commit(self)
	sys.call("/etc/init.d/drcom-auto-login restart >/dev/null 2>&1")
end

return m
