from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
script = (ROOT / "drcom/usr/bin/drcom-auto-login").read_text(encoding="utf-8")
config = (ROOT / "drcom/etc/config/drcom").read_text(encoding="utf-8")
cbi = (ROOT / "drcom/usr/lib/lua/luci/model/cbi/drcom/main.lua").read_text(encoding="utf-8")

for token in ("config_get OPERATOR", "apply_operator_profile", "china_broadnet", "R3=4", "R6=0", "TERMINAL_TYPE=1", "VERSION=6780", "LOGIN_USERNAME"):
    assert token in script, token
for token in ("option operator 'free'", "option user_suffix ''"):
    assert token in config, token
for token in ("ListValue, \"operator\"", "china_mobile", "china_unicom", "china_telecom", "china_broadnet", "user_suffix"):
    assert token in cbi, token
assert "--data-urlencode \"DDDDD=$LOGIN_USERNAME\"" in script
print("test_drcom_operator: PASS")
