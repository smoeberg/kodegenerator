#!/bin/sh
set -eu

exec python -m scripts.runtime_entrypoint "$@"
