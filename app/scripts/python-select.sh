# Sourced by setup.sh and run.sh. No downloading or global Python modifications.
find_python() {
  if [ -n "${BEEPERLOCAL_PYTHON:-}" ]; then
    if "$BEEPERLOCAL_PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' >/dev/null 2>&1; then
      printf '%s\n' "$BEEPERLOCAL_PYTHON"
      return 0
    fi
    return 1
  fi
  for candidate in python3.14 python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' >/dev/null 2>&1; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}
