"""Distribution/import contracts for the extracted Windows companion."""

from __future__ import annotations

import ast
import importlib
import io
import sys
import tempfile
import types
import unittest
from pathlib import Path
from zipfile import ZipFile

import addonAPIVersion
from configobj import ConfigObj
from configobj.validate import Validator

import build
import buildVars
from tests import NVDA_SOURCE, WIRE_ROOT
from tests._objects import install_handler_runtime_stubs


class BuildTests(unittest.TestCase):
	def test_manifest_validates_with_nvda_manifest_loader(self):
		path = NVDA_SOURCE / "addonHandler/__init__.py"
		tree = ast.parse(path.read_text(encoding="utf-8"))
		selected = [
			node
			for node in tree.body
			if isinstance(node, (ast.ClassDef, ast.FunctionDef))
			and node.name in ("AddonManifest", "validate_apiVersionString")
		]
		self.assertEqual(len(selected), 2, "NVDA manifest validation API changed")
		module = ast.Module(
			body=[
				ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
				*selected,
			],
			type_ignores=[],
		)
		namespace = {
			"ConfigObj": ConfigObj,
			"StringIO": io.StringIO,
			"Validator": Validator,
			"addonAPIVersion": addonAPIVersion,
		}
		exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
		manifest = namespace["AddonManifest"](io.BytesIO(build.entries(buildVars.VERSION)["manifest.ini"]))
		self.assertIsNone(manifest.errors)
		self.assertEqual(manifest["name"], "linuxRdAccess")
		self.assertEqual(manifest["minimumNVDAVersion"], (2026, 1, 0))
		self.assertEqual(manifest["lastTestedNVDAVersion"], (2026, 2, 0))

	def test_bundle_has_runtime_license_docs_and_one_ipc_source(self):
		with tempfile.TemporaryDirectory() as directory:
			package = build.build(Path(directory))
			with ZipFile(package) as archive:
				self.assertIsNone(archive.testzip())
				names = archive.namelist()
				self.assertEqual(len(names), len(set(names)))
				for required in ("manifest.ini", "COPYING.txt", "NOTICE.md", "doc/en/readme.html"):
					self.assertIn(required, names)
				for name in build.WIRE_MODULES:
					self.assertEqual(
						archive.read(f"globalPlugins/linuxRdAccess/{name}.py"),
						(WIRE_ROOT / f"{name}.py").read_bytes(),
					)
				for name in names:
					self.assertNotIn("rdAccess/", name)
					self.assertFalse(name.endswith((".dll", ".pyc", ".bin")))
					if name.endswith(".py"):
						ast.parse(archive.read(name).decode("utf-8"), filename=name)
				manifest = dict(
					line.split(" = ", 1) for line in archive.read("manifest.ini").decode().splitlines()
				)
				self.assertEqual(manifest["name"], "linuxRdAccess")
				self.assertEqual(manifest["version"], buildVars.VERSION)

	def test_packaged_runtime_imports_without_rdaccess_or_repository_modules(self):
		install_handler_runtime_stubs()
		with tempfile.TemporaryDirectory() as directory:
			package = build.build(Path(directory))
			with ZipFile(package) as archive:
				archive.extractall(Path(directory) / "unpacked")
			name = "_linux_rdaccess_bundle_tests"
			module = types.ModuleType(name)
			module.__path__ = [str(Path(directory) / "unpacked/globalPlugins/linuxRdAccess")]
			sys.modules[name] = module
			try:
				for child in (
					"localTestService",
					"localTestStatus",
					"remoteAccessSemanticBraille",
					"scriptedMessageRouting",
					*build.WIRE_MODULES,
				):
					imported = importlib.import_module(f"{name}.{child}")
					self.assertTrue(Path(imported.__file__).is_relative_to(Path(directory)))
			finally:
				for key in list(sys.modules):
					if key.startswith(name):
						sys.modules.pop(key)

	def test_build_is_reproducible_and_version_cannot_escape_output_directory(self):
		with tempfile.TemporaryDirectory() as directory:
			first = build.build(Path(directory) / "first").read_bytes()
			second = build.build(Path(directory) / "second").read_bytes()
			self.assertEqual(first, second)
		for version in ("../bad", "1.0.0\nkey = value", "", "1.0.0-dev"):
			with self.assertRaises(ValueError):
				build.entries(version)
