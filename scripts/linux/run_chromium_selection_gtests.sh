#!/usr/bin/env bash
# Run real, compiled upstream Chromium ATK selection gtests against the pinned patch.
# This is deliberately opt-in: a two-file source-contract test is NOT a Chromium build.
set -euo pipefail

usage() {
  echo "Usage: $0 CHROMIUM_SRC [OUT_DIR]" >&2
  echo "Requires a complete Chromium 150.0.7871.250 checkout, depot_tools, GN and a C++ toolchain." >&2
}
if [[ ${1:-} == "--help" || $# -lt 1 || $# -gt 2 ]]; then
  usage
  [[ ${1:-} == "--help" ]] && exit 0
  exit 2
fi
src="$(realpath "$1")"
out="${2:-out/Default}"
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
patch="$repo/docs/upstream/chromium-unicode-selection.diff"
evidence="${CHROMIUM_GTEST_EVIDENCE:-$repo/chromium-gtest-evidence}"
mkdir -p "$evidence"
test -f "$src/.gn" || { echo "ERROR: Not a complete Chromium source checkout: $src" >&2; exit 2; }
test -f "$src/ui/accessibility/platform/ax_platform_node_auralinux.cc" || exit 2
command -v autoninja >/dev/null || { echo "ERROR: autoninja (depot_tools) unavailable" >&2; exit 2; }
command -v gn >/dev/null || { echo "ERROR: gn (depot_tools) unavailable" >&2; exit 2; }
# Reject a mismatched Chromium revision even when the patch happens to apply.
printf '%s  %s\n' \
  '1d50dc6645c011e6fa2f036c2b08f7bb35967a60dbda12d52d55e901e8dd731f' "$src/ui/accessibility/platform/ax_platform_node_auralinux.cc" \
  'f18932d4de877d2074b541b4b77bfb9321e4292c5bf62df5a3d32c96481af540' "$src/ui/accessibility/platform/ax_platform_node_auralinux_unittest.cc" \
  | sha256sum --check | tee "$evidence/baseline-hashes.log"
git -C "$src" diff --quiet -- ui/accessibility/platform/ax_platform_node_auralinux.cc ui/accessibility/platform/ax_platform_node_auralinux_unittest.cc || {
  echo "ERROR: Target Chromium files already have unstaged changes" >&2; exit 2;
}
git -C "$src" diff --cached --quiet -- ui/accessibility/platform/ax_platform_node_auralinux.cc ui/accessibility/platform/ax_platform_node_auralinux_unittest.cc || {
  echo "ERROR: Target Chromium files already have staged changes" >&2; exit 2;
}
commit="$(git -C "$src" rev-parse HEAD)"
printf '%s\n' "$commit" > "$evidence/source-commit.txt"
# A source tree with an already-applied patch cannot establish an unmodified baseline.
git -C "$src" apply --check "$patch" || {
  echo "ERROR: Patch does not apply cleanly; check version or existing modifications" >&2; exit 2;
}
# Intentionally leave the candidate patch applied for inspection, rather than restoring a
# huge checkout after a failed build. Only the two target files are modified.
git -C "$src" apply "$patch"
printf '%s\n' 'candidate patch applied' > "$evidence/patch-state.txt"
if [[ ! -f "$src/$out/build.ninja" ]]; then
  echo "ERROR: $out/build.ninja missing. Run gn gen with appropriate Linux args first." >&2
  exit 2
fi
(
  cd "$src"
  set -o pipefail
  autoninja -C "$out" accessibility_unittests 2>&1 | tee "$evidence/build.log"
  binary="$out/accessibility_unittests"
  test -x "$binary" || { echo "ERROR: Compiled accessibility_unittests not found" >&2; exit 2; }
  "$binary" --gtest_list_tests > "$evidence/test-list.txt"
  grep -q 'TestAtkTextGetSelectionUnicodeOffsets' "$evidence/test-list.txt" || {
    echo "ERROR: Expected upstream patch gtests not linked into accessibility_unittests" >&2; exit 2;
  }
  "$binary" --gtest_filter='AXPlatformNodeAuraLinuxTest.TestAtkTextGetSelection*' \
    --gtest_output="xml:$evidence/selection-gtests.xml" 2>&1 | tee "$evidence/test.log"
)
echo "Compiled upstream test evidence: $evidence"
