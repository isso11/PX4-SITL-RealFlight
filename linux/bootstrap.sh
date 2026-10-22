#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "Build stopped at line %s. Fix the reported error and run 2-Build-SITL.cmd again.\n" "$LINENO" >&2' ERR
config="${1:?settings.json path required}"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
[[ "$(id -u)" -ne 0 ]] || { echo 'Use your normal Ubuntu user, not root.' >&2; exit 1; }
command -v python3 >/dev/null || { echo 'Install python3 in Ubuntu first: sudo apt-get install python3' >&2; exit 1; }
config_fields="$(python3 "$script_dir/sitl.py" "$config" settings)"
mapfile -t fields <<< "$config_fields"
base="$HOME/${fields[0]}"
px4_ref="${fields[1]}"
bridge_ref="${fields[2]}"
px4="$base/PX4-Autopilot"
bridge="$base/PX4-FlightAxis-Bridge"
mkdir -p "$base"
exec 9>"$base/.build.lock"
flock -n 9 || { echo 'Another build is running in this workspace.' >&2; exit 1; }
if [[ -f "$base/run/launcher.json" ]]; then
    echo 'Stop SITL before rebuilding (4-Stop-SITL.cmd). If it crashed, run the stop command to clear stale session metadata.' >&2
    exit 1
fi
if ! command -v git >/dev/null; then
    sudo apt-get update
    sudo apt-get install -y git
fi
clone_if_missing() {
    local url="$1" ref="$2" dest="$3"
    if [[ -d "$dest/.git" ]]; then
        [[ "$(git -C "$dest" remote get-url origin)" == "$url" ]] || { echo "Unexpected origin in $dest" >&2; exit 1; }
    elif [[ -e "$dest" ]]; then
        echo "Existing non-repository path: $dest. No files were overwritten." >&2
        exit 1
    else
        # A full commit ID is not a branch name. Clone first, then resolve the
        # configured tag, branch or commit without tracking a moving branch.
        git clone --no-checkout "$url" "$dest"
        git -C "$dest" checkout --detach "$ref"
    fi
}
clone_if_missing https://github.com/PX4/PX4-Autopilot.git "$px4_ref" "$px4"
git -C "$px4" submodule update --init --recursive
clone_if_missing https://github.com/evandas11/PX4-FlightAxis-Bridge.git "$bridge_ref" "$bridge"
python3 "$script_dir/sitl.py" "$config" lock
if [[ ! -f "$base/.toolchain-ready" ]]; then
    sudo apt-get update
    sudo apt-get install -y build-essential cmake ninja-build libeigen3-dev python3-pip python3-venv rsync procps
    bash "$px4/Tools/setup/ubuntu.sh" --no-nuttx --no-sim-tools
    touch "$base/.toolchain-ready"
fi
bash "$bridge/install.sh" "$px4" --yes
python3 "$script_dir/sitl.py" "$config" mark-built
echo 'PX4 and FlightAxis bridge build completed. Use 3-Start-SITL.cmd next.'
