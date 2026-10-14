"""Build the source-only Windows NVDA companion using Python's standard library."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import buildVars

ROOT = Path(__file__).resolve().parent
WIRE_ROOT = ROOT.parent / "linux_rdaccess_core/connection/nvda_test_client"
WIRE_MODULES = (
	"localTestIpc",
	"localTestRequest",
	"localTestRoutingTrace",
	"localTestTransport",
	"localTestWindows",
)


def entries(version: str) -> dict[str, bytes]:
	if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
		raise ValueError("Version must have three numeric components")
	manifest = (
		f"name = {buildVars.NAME}\n"
		f"summary = {buildVars.SUMMARY}\n"
		f"description = {buildVars.DESCRIPTION}\n"
		f"author = {buildVars.AUTHOR}\n"
		f"version = {version}\n"
		f"minimumNVDAVersion = {buildVars.MINIMUM_NVDA}\n"
		f"lastTestedNVDAVersion = {buildVars.LAST_TESTED_NVDA}\n"
		f"url = {buildVars.URL}\n"
		f"sourceURL = {buildVars.URL}\n"
		"docFileName = readme.html\n"
		"updateChannel = dev\n"
		"license = GPL 2.0 or later\n"
	)
	result = {"manifest.ini": manifest.encode("utf-8")}
	for path in sorted((ROOT / "addon/globalPlugins/linuxRdAccess").glob("*.py")):
		result[path.relative_to(ROOT / "addon").as_posix()] = path.read_bytes()
	for name in WIRE_MODULES:
		entry = f"globalPlugins/linuxRdAccess/{name}.py"
		if entry in result:
			raise ValueError("IPC modules must have a single source in nvda_test_client")
		result[entry] = (WIRE_ROOT / f"{name}.py").read_bytes()
	for name in ("COPYING.txt", "NOTICE.md"):
		result[name] = (ROOT / name).read_bytes()
	result["doc/en/readme.html"] = (ROOT / "addon/doc/en/readme.html").read_bytes()
	return result


def build(output: Path, version: str = buildVars.VERSION) -> Path:
	content = entries(version)
	output.mkdir(parents=True, exist_ok=True)
	package = output / f"{buildVars.NAME}-{version}.nvda-addon"
	with ZipFile(package, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
		for name, data in sorted(content.items()):
			info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
			info.create_system = 3
			info.external_attr = 0o100644 << 16
			info.compress_type = ZIP_DEFLATED
			archive.writestr(info, data, compresslevel=9)
	return package


def main() -> None:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--version", default=buildVars.VERSION)
	parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
	args = parser.parse_args()
	print(build(args.output_dir, args.version))


if __name__ == "__main__":
	main()
