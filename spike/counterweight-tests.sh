#!/usr/bin/env bash
# Run counterweight's emulator tests against spike/emulator.py's evp-based Emulator.
#
# Usage: spike/counterweight-tests.sh PYTHON COUNTERWEIGHT_CHECKOUT [PYTEST_ARGS...]
# PYTHON must have evp, pytest, and counterweight (from that checkout) installed.
# The overscan test inspects counterweight's own capture internals, which evp replaces, so it's skipped.

set -euo pipefail

python="$1"
counterweight="$2"
shift 2

spike="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
tests="$(mktemp -d)"
trap 'rm -rf "$tests"' EXIT

sed 's/^from counterweight.emulator import Emulator$/from emulator import EvpEmulator as Emulator/' \
  "$counterweight/tests/test_emulator.py" > "$tests/test_emulator_on_evp.py"
grep -q "EvpEmulator" "$tests/test_emulator_on_evp.py"

cd "$tests"
PYTHONPATH="$spike" "$python" -m pytest -p no:cacheprovider -k "not captures_twice" "$@" test_emulator_on_evp.py
