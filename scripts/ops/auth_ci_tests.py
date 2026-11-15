"""Run synthetic CI tests and expose bounded failure summaries as annotations.

Never run against production: fixture suites create and drop isolated schemas.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
suite = unittest.defaultTestLoader.loadTestsFromNames(sys.argv[1:])
result = unittest.TextTestRunner(verbosity=2).run(suite)
for test, failure in result.failures + result.errors:
    # Synthetic test output only; no real user records or production configuration.
    message = (str(test) + "\n" + failure[-3500:]).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print("::error title=Isolated test failure::" + message)
sys.exit(0 if result.wasSuccessful() else 1)
