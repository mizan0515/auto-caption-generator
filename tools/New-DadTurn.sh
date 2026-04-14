#!/usr/bin/env sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$script_dir/_ps1_runner.sh" "$script_dir/New-DadTurn.ps1" "$@"
