#!/usr/bin/env bash
# Fail-closed launcher for the mcp-mail outbound-send gate.
#
# PreToolUse treats ANY exit code other than 0 or 2 as NON-blocking: on such an
# exit the tool call PROCEEDS (fail-open). A crash, a missing interpreter (127),
# or a syntax error (1) in the python gate would therefore let a send through.
# This wrapper forces every exit that is not the gate's own 0 (allow) or 2
# (deny) into a blocking exit 2, closing that gap. The gate's real verdicts pass
# through untouched. stdin (the hook's JSON) flows through to the python gate.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${MAIL_SEND_GATE_PY:-$DIR/mail_send_gate.py}"
PYBIN="${MAIL_SEND_GATE_PYTHON:-python3}"

"$PYBIN" "$PY"
rc=$?
if [ "$rc" -eq 0 ] || [ "$rc" -eq 2 ]; then
  exit "$rc"
fi
echo "send-gate: internal error (rc=$rc); blocking to fail closed." >&2
exit 2
