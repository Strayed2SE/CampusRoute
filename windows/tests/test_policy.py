import tempfile, pathlib, unittest, sys
sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import campusroute
from unittest.mock import patch

class PolicyTests(unittest.TestCase):
    def test_domestic_private(self):
        p=campusroute.PolicyEngine(dict(campusroute.DEFAULT_CONFIG))
        self.assertTrue(p.domestic('192.168.1.1'))
    def test_unknown_reject_without_usb(self):
        c=dict(campusroute.DEFAULT_CONFIG); c['usb_missing_fallback']=False
        p=campusroute.PolicyEngine(c); p.usb_online=lambda:False
        self.assertEqual(p.decide('8.8.8.8','tcp',443),'reject')
    def test_unknown_fallback(self):
        c=dict(campusroute.DEFAULT_CONFIG); c['usb_missing_fallback']=True
        p=campusroute.PolicyEngine(c); p.usb_online=lambda:False
        self.assertEqual(p.decide('8.8.8.8','tcp',443),'campus')
    def test_cn_file(self):
        old=campusroute.RULES_PATH
        with tempfile.TemporaryDirectory() as d:
            campusroute.RULES_PATH=pathlib.Path(d)/'cn.txt'; campusroute.RULES_PATH.write_text('1.0.1.0/24')
            p=campusroute.PolicyEngine(dict(campusroute.DEFAULT_CONFIG)); self.assertTrue(p.domestic('1.0.1.2'))
        campusroute.RULES_PATH=old
    def test_drcom_json_result(self):
        class Resp:
            def __enter__(self): return self
            def __exit__(self,*a): pass
            def read(self,n): return b'dr1003({"result":1,"uid":"x"})'
        with patch('urllib.request.urlopen', return_value=Resp()):
            ok,_=campusroute.PortalClient('http://HOST/drcom/login').login('u','p')
            self.assertTrue(ok)

    def test_ipv6_extension_header(self):
        # IPv6 + hop-by-hop header + UDP/443 must still expose the destination
        # and encrypted-port classification.
        import ipaddress
        base = bytearray(40)
        base[0] = 0x60
        base[6] = 0  # hop-by-hop
        base[24:40] = ipaddress.IPv6Address('2001:4860:4860::8888').packed
        ext = bytearray(8); ext[0] = 17; ext[1] = 0
        udp = bytearray(8); udp[0:2] = (12345).to_bytes(2, 'big'); udp[2:4] = (443).to_bytes(2, 'big')
        parsed = campusroute._parse_packet(bytes(base + ext + udp))
        self.assertEqual(parsed, ('2001:4860:4860::8888', 'udp', 443))

    def test_service_fixed_commands(self):
        service = campusroute.Service()
        self.assertFalse(service.handle({'cmd': 'arbitrary-shell'})['ok'])
        self.assertIn('backend', service.handle({'cmd': 'status'}))

    def test_build_and_install_contract(self):
        root = pathlib.Path(__file__).parents[1]
        build = (root / 'build.ps1').read_text(encoding='utf-8')
        install = (root / 'install.ps1').read_text(encoding='utf-8')
        uninstall = (root / 'uninstall.ps1').read_text(encoding='utf-8')
        rollback = (root / 'rollback.ps1').read_text(encoding='utf-8')
        for token in ('--onefile', '--add-binary', 'WinDivert64.sys', 'Authenticode', 'SHA256'):
            self.assertIn(token, build)
        for token in ('New-Service', 'CampusRoute Panic Block', 'schtasks.exe', 'routes-before.json'):
            self.assertIn(token, install)
        for token in ('--purge-credentials', 'advfirewall import', 'Remove-NetFirewallRule', '-PurgeData'):
            self.assertIn(token, uninstall)
        self.assertIn('--rollback', rollback)

if __name__=='__main__': unittest.main()
