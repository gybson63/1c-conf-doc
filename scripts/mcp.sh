#!/usr/bin/env sh
exec "$(dirname "$0")/../.venv/bin/python" -m onec_conf_doc.mcp "$@"
