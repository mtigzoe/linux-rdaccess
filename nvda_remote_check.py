#!/usr/bin/env python3
"""Backward-compatible NVDA Remote connection diagnostic entry point.

The implementation lives in linux_rdaccess_core.connection.nvda_remote_check.
"""
from linux_rdaccess_core.connection.nvda_remote_check import *  # noqa: F401,F403

if __name__ == "__main__":
    raise SystemExit(main())
