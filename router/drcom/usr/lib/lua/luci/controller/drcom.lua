local http = require "luci.http"
local sys  = require "luci.sys"

module("luci.controller.drcom", package.seeall)

function index()
	-- Keep the existence check dependency-free.  Some QWRT LuCI builds
	-- serialize index() and do not restore the nixio upvalue on reload.
	local f = io.open("/etc/config/drcom", "r")
	if not f then return end
	f:close()

	local page = entry({"admin", "services", "drcom"}, cbi("drcom/main"), _("Dr.COM 认证"), 31)
	page.dependent = true
	page.acl_depends = { "luci-app-drcom" }

	entry({"admin", "services", "drcom", "status"}, call("action_status")).leaf = true
	entry({"admin", "services", "drcom", "login"}, call("action_login")).leaf = true
end

function action_status()
	local text = sys.exec("/usr/bin/drcom-auto-login --status 2>/dev/null")
	http.prepare_content("application/json")
	http.write_json({ status = text:gsub("%s+$", "") })
end

function action_login()
	if http.getenv("REQUEST_METHOD") ~= "POST" then
		http.status(405, "Method Not Allowed")
		return
	end
	local rc = sys.call("/usr/bin/drcom-auto-login --once >/dev/null 2>&1")
	http.prepare_content("application/json")
	http.write_json({ ok = (rc == 0) })
end
