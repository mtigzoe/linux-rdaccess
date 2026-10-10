"""Tests for read-only diagnostics MCP; never touch a live desktop."""
import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[3] / "tools/mcp/linux_rdaccess_mcp.py"
spec = importlib.util.spec_from_file_location("read_only_mcp", SCRIPT)
mcp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcp)


class McpTests(unittest.TestCase):
    def test_initialize(self):
        out = mcp.dispatch({"id": 1, "method": "initialize"})
        self.assertEqual(out["result"]["serverInfo"]["name"], "linux-rdaccess-diagnostics")

    def test_tool_list(self):
        out = mcp.dispatch({"id": 2, "method": "tools/list"})
        self.assertEqual({item["name"] for item in out["result"]["tools"]},
                         {"atspi_status", "atspi_event_counts", "x11_status"})

    def test_rejects_unknown_calls(self):
        for name, arguments in [("shell", {}), ("atspi_status", {"command": "ls"})]:
            out = mcp.dispatch({"id": 3, "method": "tools/call",
                                "params": {"name": name, "arguments": arguments}})
            self.assertEqual(out["error"]["code"], -32602)

    def test_rejects_bad_limits(self):
        for limit in (True, -1, 21, "5"):
            with self.assertRaises(ValueError):
                mcp.tool_command("atspi_status", {"limit": limit})
        for seconds in (True, 0, 16, "5"):
            with self.assertRaises(ValueError):
                mcp.tool_command("atspi_event_counts", {"seconds": seconds})

    def test_no_remote_display(self):
        with patch.dict(mcp.os.environ, {"DISPLAY": "localhost:10"}):
            with self.assertRaises(ValueError):
                mcp.tool_command("x11_status", {})

    def test_existing_diagnostic_invocation(self):
        cmd, seconds = mcp.tool_command("atspi_status", {"limit": 2})
        self.assertEqual(cmd[-2:], ["--limit", "2"])
        self.assertIn("diagnostics/atspi/atspi_probe.py", cmd[1])
        self.assertEqual(seconds, 10)

    def test_diagnostic_failures_do_not_leak_stderr(self):
        with patch.object(mcp.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "SECRET")):
            out = mcp.dispatch({"id": 4, "method": "tools/call",
                                "params": {"name": "atspi_status", "arguments": {}}})
            self.assertTrue(out["result"]["isError"])
            self.assertNotIn("SECRET", out["result"]["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
