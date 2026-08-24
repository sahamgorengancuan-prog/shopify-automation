#!/usr/bin/env bash
# =====================================================================
#  ARCHIVIST — full pipeline launcher for Ubuntu 24.04 (and friends)
#
#    ./archivist.sh setup                 install everything
#    ./archivist.sh app                   launch the Gradio control room
#    ./archivist.sh app --host 0.0.0.0    serve it on the network
#    ./archivist.sh check                 connection self-test
#    ./archivist.sh house                 V9 house system end to end
#    ./archivist.sh house --topic harbor  house system on a chosen signal
#    ./archivist.sh volume                rank roots by relative search volume
#    ./archivist.sh run "deep sea salvage" [--no-generate ...]
#    ./archivist.sh plan "north sea oil" -n 6 --create
#    ./archivist.sh scheduler             run the scheduler headless
#    ./archivist.sh service               install a systemd unit
#    ./archivist.sh test                  run the test suite
#    ./archivist.sh doctor                what is installed, what is missing
#
#  Ubuntu 24.04 ships Python 3.12 and enforces PEP 668, so everything is
#  installed into a virtualenv under the project — never into system Python.
# =====================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$HERE"
[[ -f "$ROOT/requirements.txt" ]] || ROOT="$(cd "$HERE/../.." && pwd)"
cd "$ROOT"

VENV="${ARCHIVIST_VENV:-$ROOT/.venv}"
PY="$VENV/bin/python"
PORT="${ARCHIVIST_PORT:-7860}"
PYTHON_MIN_MINOR=10

c_reset=$'\033[0m'; c_dim=$'\033[2m'; c_ok=$'\033[32m'; c_warn=$'\033[33m'; c_err=$'\033[31m'; c_bold=$'\033[1m'
say()  { printf '%s\n' "  $*"; }
ok()   { printf '%s\n' "  ${c_ok}[ok]${c_reset} $*"; }
warn() { printf '%s\n' "  ${c_warn}[!!]${c_reset} $*"; }
die()  { printf '%s\n' "  ${c_err}[xx]${c_reset} $*" >&2; exit 1; }
banner() { printf '\n  %sARCHIVIST%s %s\n  %s\n\n' "$c_bold" "$c_reset" "$1" "${c_dim}$(printf '─%.0s' {1..58})${c_reset}"; }

as_root() { if [[ $EUID -eq 0 ]]; then "$@"; else sudo "$@"; fi; }

# --- interpreter -----------------------------------------------------
pick_python() {
    local candidate
    for candidate in python3.14 python3.13 python3.12 python3; do
        if command -v "$candidate" >/dev/null 2>&1; then
            if "$candidate" -c "import sys; raise SystemExit(0 if sys.version_info>=(3,$PYTHON_MIN_MINOR) else 1)"; then
                echo "$candidate"
                return 0
            fi
        fi
    done
    return 1
}

apt_deps() {
    command -v apt-get >/dev/null 2>&1 || return 0
    local missing=()
    dpkg -s python3-venv >/dev/null 2>&1 || missing+=(python3-venv)
    dpkg -s python3-pip  >/dev/null 2>&1 || missing+=(python3-pip)
    # Pillow ships manylinux wheels, so no build deps are needed; curl is used
    # by the deploy helpers and the health check.
    command -v curl >/dev/null 2>&1 || missing+=(curl)
    [[ ${#missing[@]} -eq 0 ]] && return 0

    say "missing system packages: ${missing[*]}"
    if [[ $EUID -eq 0 ]]; then
        apt-get update -qq && apt-get install -y -qq "${missing[@]}"
    elif command -v sudo >/dev/null 2>&1; then
        sudo apt-get update -qq && sudo apt-get install -y -qq "${missing[@]}"
    else
        die "install them first:  sudo apt-get install -y ${missing[*]}"
    fi
    ok "system packages installed"
}

cmd_setup() {
    banner "setup"
    apt_deps
    local base
    base="$(pick_python)" || die "no Python >= 3.$PYTHON_MIN_MINOR found. Try: sudo apt-get install -y python3.12"
    ok "using $base ($("$base" -V 2>&1))"

    if [[ ! -x "$PY" ]]; then
        say "creating the virtualenv in ${VENV#$ROOT/}"
        "$base" -m venv "$VENV" || die "venv creation failed (sudo apt-get install -y python3-venv)"
    fi
    "$PY" -m pip install --upgrade pip --quiet
    say "installing dependencies"
    "$PY" -m pip install -r "$ROOT/requirements.txt" --quiet || die "dependency install failed"

    if [[ ! -f "$ROOT/.env" && -f "$ROOT/.env.example" ]]; then
        cp "$ROOT/.env.example" "$ROOT/.env"
        ok "created .env — add your keys there, or use the Setup tab in the app"
    fi
    ok "setup complete"
    say "next:  ./scripts/linux/archivist.sh app"
}

ensure_env() {
    [[ -x "$PY" ]] || { say "environment missing — running setup first"; cmd_setup; }
}

# --- commands --------------------------------------------------------
cmd_app() {
    ensure_env
    banner "control room"
    local args=("$@")
    if [[ ${#args[@]} -eq 0 ]]; then
        args=(--port "$PORT")
    fi
    say "open http://127.0.0.1:$PORT   (ctrl-c to stop)"
    exec "$PY" -m archivist.app "${args[@]}"
}

cmd_run()       { ensure_env; exec "$PY" -m archivist run "$@"; }
cmd_house()     { ensure_env; banner "house system"; exec "$PY" -m archivist house "$@"; }
cmd_volume()    { ensure_env; exec "$PY" -m archivist volume "$@"; }
cmd_check()     { ensure_env; exec "$PY" -m archivist check "$@"; }
cmd_plan()      { ensure_env; exec "$PY" -m archivist plan "$@"; }
cmd_runs()      { ensure_env; exec "$PY" -m archivist runs "$@"; }
cmd_jobs()      { ensure_env; exec "$PY" -m archivist jobs "$@"; }
cmd_scheduler() { ensure_env; banner "scheduler"; exec "$PY" -m archivist serve-scheduler "$@"; }
cmd_deploy()    { ensure_env; exec "$PY" -m archivist deploy "$@"; }

cmd_test() {
    ensure_env
    banner "tests"
    "$PY" -m pip install pytest --quiet
    exec "$PY" -m pytest -q "$ROOT/tests"
}

cmd_service() {
    ensure_env
    banner "systemd service"
    local unit="/etc/systemd/system/archivist.service"
    "$PY" -m archivist deploy --target "$ROOT/deploy" --port "$PORT" \
        --user "${SUDO_USER:-$USER}" --workdir "$ROOT" >/dev/null
    say "unit written to deploy/archivist.service"
    if [[ $EUID -ne 0 ]] && ! command -v sudo >/dev/null 2>&1; then
        warn "run as root (or install sudo) to register it"
        return 0
    fi
    as_root cp "$ROOT/deploy/archivist.service" "$unit"
    as_root systemctl daemon-reload
    as_root systemctl enable --now archivist
    ok "archivist.service enabled — journalctl -u archivist -f"
}

cmd_doctor() {
    banner "doctor"
    printf '  %-22s %s\n' "project" "$ROOT"
    printf '  %-22s %s\n' "venv" "$([[ -x "$PY" ]] && "$PY" -V 2>&1 || echo 'not created')"
    printf '  %-22s %s\n' "system python" "$(pick_python 2>/dev/null || echo none)"
    printf '  %-22s %s\n' "os" "$( (. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME") || uname -sr)"
    printf '  %-22s %s\n' ".env" "$([[ -f "$ROOT/.env" ]] && echo present || echo missing)"
    printf '  %-22s %s\n' "runs" "$(du -sh "${ARCHIVIST_RUNS_DIR:-$ROOT/runs}" 2>/dev/null | cut -f1 || echo '0')"
    printf '  %-22s %s\n' "disk free" "$(df -h "$ROOT" | awk 'NR==2{print $4}')"
    if [[ -x "$PY" ]]; then
        echo
        "$PY" -m archivist check || true
    else
        warn "run ./archivist.sh setup first"
    fi
}

cmd_all() {
    # setup -> check -> one offline run -> launch the UI: the whole thing, once.
    cmd_setup
    "$PY" -m archivist check || true
    banner "demonstration run (offline, no keys needed)"
    "$PY" -m archivist --offline run "${1:-municipal water infrastructure}" --no-generate
    cmd_app
}

usage() {
    sed -n '2,21p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

main() {
    local command="${1:-app}"
    shift || true
    case "$command" in
        setup)      cmd_setup "$@" ;;
        app|ui|gui) cmd_app "$@" ;;
        run)        cmd_run "$@" ;;
        house)      cmd_house "$@" ;;
        volume)     cmd_volume "$@" ;;
        check)      cmd_check "$@" ;;
        plan)       cmd_plan "$@" ;;
        runs)       cmd_runs "$@" ;;
        jobs)       cmd_jobs "$@" ;;
        scheduler)  cmd_scheduler "$@" ;;
        deploy)     cmd_deploy "$@" ;;
        service)    cmd_service "$@" ;;
        test)       cmd_test "$@" ;;
        doctor)     cmd_doctor "$@" ;;
        all)        cmd_all "$@" ;;
        -h|--help|help) usage ;;
        *)          warn "unknown command: $command"; usage; exit 2 ;;
    esac
}

main "$@"
