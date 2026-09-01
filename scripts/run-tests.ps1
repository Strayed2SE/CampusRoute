$ErrorActionPreference = 'Stop'
python router/tests/test_static.py
python router/tests/test_fixture.py
python router/tests/test_failover.py
python router/tests/test_incremental.py
python router/tests/test_accel.py
python router/tests/test_drcom_operator.py
python -m unittest discover -s windows/tests -v
python -m py_compile windows/campusroute.py
Write-Host 'CampusRoute tests: PASS'
