#!/usr/bin/env python3
"""Compile two pinned Chromium selection methods with small test dependencies.

This is a source-extraction contract, not a Chromium build, upstream gtest run,
or native ATK/AT-SPI test. The C++ selection methods come unchanged from the
source under test. ATK, the selection delegate, and Unicode conversion are test
doubles; the converter rejects offsets inside UTF-16 surrogate pairs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

SOURCE_SHA256 = "1d50dc6645c011e6fa2f036c2b08f7bb35967a60dbda12d52d55e901e8dd731f"
SOURCE_PATH = Path("ui/accessibility/platform/ax_platform_node_auralinux.cc")


def extract_method(source: str, name: str) -> str:
    """Extract the complete named method, retaining its actual C++ body."""
    marker = f"AXPlatformNodeAuraLinux::{name}("
    if source.count(marker) != 1:
        raise ValueError(f"Expected one {marker}")
    method = source.index(marker)
    start = source.rfind("\n", 0, method) + 1
    opening = source.index("{", method)
    depth = 0
    for end in range(opening, len(source)):
        if source[end] == "{":
            depth += 1
        elif source[end] == "}":
            depth -= 1
            if depth == 0:
                return source[start : end + 1]
    raise ValueError(f"Unclosed method {name}")


HARNESS = r"""
#include <algorithm>
#include <codecvt>
#include <cstdlib>
#include <iostream>
#include <locale>
#include <optional>
#include <string>
#include <utility>

using gchar = char;
class AXPlatformNodeAuraLinux;
struct AtkObject { AXPlatformNodeAuraLinux* owner; };
struct FindInPageResultInfo { AtkObject* node; int start_offset; int end_offset; };
#define ATK_TEXT(object) (object)

class AXPlatformNodeAuraLinux {
 public:
  std::u16string text;
  std::pair<int, int> selection = {0, 0};
  AtkObject object = {this};
  std::optional<FindInPageResultInfo> find;
  std::pair<int, int> GetSelectionOffsetsForAtk() { return selection; }
  AtkObject* GetOrCreateAtkObject() { return &object; }
  std::optional<FindInPageResultInfo> GetSelectionOffsetsFromFindInPage() {
    return find;
  }
  // Controlled test dependency; production OffsetAdjuster is not linked.
  size_t UTF16ToUnicodeOffsetInText(size_t offset) {
    if (offset > text.size()) return std::u16string::npos;
    size_t units = 0;
    size_t points = 0;
    while (units < offset) {
      const bool pair = text[units] >= 0xd800 && text[units] <= 0xdbff &&
          units + 1 < text.size() && text[units + 1] >= 0xdc00 &&
          text[units + 1] <= 0xdfff;
      units += pair ? 2 : 1;
      if (units > offset) return std::u16string::npos;
      ++points;
    }
    return points;
  }
  size_t UnicodeToUTF16OffsetInText(int offset) {
    if (offset < 0) return std::u16string::npos;
    size_t units = 0;
    for (int points = 0; points < offset; ++points) {
      if (units >= text.size()) return std::u16string::npos;
      const bool pair = text[units] >= 0xd800 && text[units] <= 0xdbff &&
          units + 1 < text.size() && text[units + 1] >= 0xdc00 &&
          text[units + 1] <= 0xdfff;
      units += pair ? 2 : 1;
    }
    return units;
  }
  void GetSelectionExtents(int*, int*);
  gchar* GetSelectionWithText(int*, int*);
};

namespace atk_text {
gchar* GetText(AtkObject* object, int start, int end) {
  auto* owner = object->owner;
  size_t first = owner->UnicodeToUTF16OffsetInText(start);
  size_t last = owner->UnicodeToUTF16OffsetInText(end);
  if (first == std::u16string::npos || last == std::u16string::npos ||
      first > last) return nullptr;
  std::wstring_convert<std::codecvt_utf8_utf16<char16_t>, char16_t> converter;
  std::string result = converter.to_bytes(owner->text.substr(first, last-first));
  auto* copy = static_cast<char*>(std::malloc(result.size() + 1));
  result.copy(copy, result.size());
  copy[result.size()] = '\0';
  return copy;
}
}

// ACTUAL_METHODS

int main() {
  struct Case {
    const char* name;
    std::u16string text;
    int raw_start, raw_end, start, end;
    std::u16string selected;
    bool find = false;
  };
  const Case cases[] = {
    {"bmp_full", u"a caf\u00e9 omega", 0, 12, 0, 12, u"a caf\u00e9 omega"},
    {"emoji_full", u"a\U0001f642 caf\u00e9 omega", 0, 14, 0, 13,
     u"a\U0001f642 caf\u00e9 omega"},
    {"emoji_suffix", u"a\U0001f642 caf\u00e9 omega", 3, 14, 2, 13,
     u" caf\u00e9 omega"},
    {"emoji_only", u"a\U0001f642 caf\u00e9 omega", 1, 3, 1, 2,
     u"\U0001f642"},
    {"emoji_reverse", u"a\U0001f642 caf\u00e9 omega", 14, 3, 2, 13,
     u" caf\u00e9 omega"},
    {"two_emoji_full", u"a\U0001f642\U0001f642 caf\u00e9 omega", 0, 16, 0, 14,
     u"a\U0001f642\U0001f642 caf\u00e9 omega"},
    {"find_emoji_full", u"a\U0001f642 caf\u00e9 omega", 0, 14, 0, 13,
     u"a\U0001f642 caf\u00e9 omega", true},
    {"find_emoji_suffix", u"a\U0001f642 caf\u00e9 omega", 3, 14, 2, 13,
     u" caf\u00e9 omega", true},
    {"no_selection", u"a\U0001f642 caf\u00e9 omega", 0, 0, 0, 0, u""},
  };
  int failures = 0;
  for (const auto& test : cases) {
    AXPlatformNodeAuraLinux node;
    node.text = test.text;
    if (test.find) {
      node.find = FindInPageResultInfo{&node.object, test.raw_start, test.raw_end};
    } else {
      node.selection = {test.raw_start, test.raw_end};
    }
    int start = -1, end = -1;
    gchar* selected = node.GetSelectionWithText(&start, &end);
    std::wstring_convert<std::codecvt_utf8_utf16<char16_t>, char16_t> converter;
    std::string expected = converter.to_bytes(test.selected);
    bool equal = expected.empty() ? selected == nullptr :
        selected && expected == selected;
    bool passed = start == test.start && end == test.end && equal;
    failures += !passed;
    std::cout << "{\"case\":\"" << test.name << "\",\"expected_start\":"
        << test.start << ",\"expected_end\":" << test.end
        << ",\"observed_start\":" << start << ",\"observed_end\":" << end
        << ",\"selected_text_equal\":" << (equal ? "true" : "false")
        << ",\"passed\":" << (passed ? "true" : "false") << "}\n";
    std::free(selected);
  }
  std::cout << "{\"passed\":" << std::size(cases) - failures
      << ",\"failed\":" << failures << "}\n";
  return failures ? 1 : 0;
}
"""


def run_contract(source: Path, patch: Path, output: Path, compiler: str) -> dict:
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != SOURCE_SHA256:
        raise ValueError(
            f"Source SHA256 differs from pinned Chromium 150.0.7871.250: {digest}"
        )
    output.mkdir(parents=True, exist_ok=False)
    candidate = output / "candidate" / SOURCE_PATH
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(raw)
    subprocess.run(
        ["git", "apply", f"--include={SOURCE_PATH.as_posix()}", str(patch.resolve())],
        cwd=output / "candidate",
        check=True,
    )
    summary = {
        "source_sha256": digest,
        "kind": "extracted_cpp_methods_with_test_dependencies",
    }
    for name, content in [
        ("original", raw.decode()),
        ("candidate", candidate.read_text()),
    ]:
        methods = "\n\n".join(
            extract_method(content, method)
            for method in ("GetSelectionExtents", "GetSelectionWithText")
        )
        cpp = output / f"{name}.cc"
        cpp.write_text(HARNESS.replace("// ACTUAL_METHODS", methods), encoding="utf-8")
        binary = output / f"{name}_contract"
        subprocess.run(
            [
                compiler,
                "-std=c++17",
                "-Wall",
                "-Wextra",
                "-Werror",
                str(cpp),
                "-o",
                str(binary),
            ],
            check=True,
        )
        result = subprocess.run(
            [str(binary.resolve())], check=False, capture_output=True, text=True
        )
        (output / f"{name}.jsonl").write_text(result.stdout, encoding="utf-8")
        if result.stderr:
            raise RuntimeError(result.stderr)
        records = [json.loads(line) for line in result.stdout.splitlines()]
        summary[name] = {**records[-1], "exit_code": result.returncode}
    summary["expected_result"] = summary["original"] == {
        "passed": 4,
        "failed": 5,
        "exit_code": 1,
    } and summary["candidate"] == {"passed": 9, "failed": 0, "exit_code": 0}
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--patch", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, required=True, help="New disposable directory"
    )
    parser.add_argument("--compiler", default="g++")
    args = parser.parse_args()
    result = run_contract(args.source, args.patch, args.output, args.compiler)
    print(json.dumps(result, indent=2))
    return 0 if result["expected_result"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
