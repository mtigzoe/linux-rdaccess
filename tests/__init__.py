import logging

logging.disable(logging.CRITICAL)  # keep expected warnings out of test output

# Keep historical fixture imports working while unit modules transition to
# the grouped test layout. The actual test modules live only in tests/shared/.
# Register aliases instead of importing their test classes into this package,
# which would cause unittest to discover duplicate cases.
import sys as _sys
from .shared import test_remote_access as test_remote_access
_sys.modules[__name__ + ".test_remote_access"] = test_remote_access
from .shared import test_compat_lifecycle as test_compat_lifecycle
_sys.modules[__name__ + ".test_compat_lifecycle"] = test_compat_lifecycle
