local http = require "luci.http"
local sys = require "luci.sys"

module("luci.controller.campus_route", package.seeall)

local function action_cmd(cmd)
	if http.getenv("REQUEST_METHOD") ~= "POST" then
		http.status(405, "Method Not Allowed")
		return
	end
	local rc = sys.call(cmd .. " >/dev/null 2>&1")
	http.prepare_content("application/json")
	http.write_json({ ok = (rc == 0), exit_code = rc })
end

function index()
	-- Do not call a module-local helper here.  QWRT's dispatcher serializes the
	-- index() function into /tmp/luci-indexcache and serialized closures lose
	-- module upvalues on reload.  Keep the existence check inline.
	local f = io.open("/etc/config/campus_route", "r")
	if not f then return end
	f:close()
	local page = entry({"admin", "services", "campus_route"}, cbi("campus_route/main"), _("Campus Route"), 32)
	page.dependent = true
	page.acl_depends = { "luci-app-campus-route" }
	entry({"admin", "services", "campus_route", "status"}, call("action_status")).leaf = true
	entry({"admin", "services", "campus_route", "apply"}, call("action_apply")).leaf = true
	entry({"admin", "services", "campus_route", "refresh"}, call("action_refresh")).leaf = true
	entry({"admin", "services", "campus_route", "start"}, call("action_start")).leaf = true
	entry({"admin", "services", "campus_route", "stop"}, call("action_stop")).leaf = true
end

function action_status()
	local out = sys.exec("/usr/bin/campus-route status 2>/dev/null")
	http.prepare_content("application/json")
	http.write(out ~= "" and out or "{\"ok\":false}")
end

function action_apply()
	action_cmd("/usr/bin/campus-route reconcile")
end

function action_refresh()
	action_cmd("/usr/bin/campus-route refresh")
end

function action_start()
	action_cmd("/etc/init.d/campus-route start")
end

function action_stop()
	action_cmd("/etc/init.d/campus-route stop")
end
