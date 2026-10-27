"""Record executed test counts and named failures; never hide a failing assertion."""
import json
from pathlib import Path
import sys
import time
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
start=time.perf_counter()
suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'))
result=unittest.TextTestRunner(verbosity=2).run(suite)
report={'tests_run':result.testsRun,'failure_count':len(result.failures),'error_count':len(result.errors),
        'skipped':len(result.skipped),'success':result.wasSuccessful(),'elapsed_s':time.perf_counter()-start,
        'failures':[{'test':str(t),'traceback':e} for t,e in result.failures],
        'errors':[{'test':str(t),'traceback':e} for t,e in result.errors]}
(ROOT/'reports/test-results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
raise SystemExit(0 if result.wasSuccessful() else 1)
