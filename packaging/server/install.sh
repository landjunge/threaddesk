#!/bin/sh
# Install only into the selected user's prefix. Never enable/start a service.
set -eu
umask 077

prefix=${1:-"$HOME/.local/share/threaddesk-server"}
origin=${2:-}
if [ "$#" -gt 2 ] || [ -z "$origin" ]; then
    echo 'Usage: sh packaging/server/install.sh /absolute/install/prefix https://server.example.org' >&2
    exit 2
fi
case "$prefix" in
    /*) ;;
    *) echo 'Installation prefix must be absolute.' >&2; exit 2 ;;
esac
# The generated systemd unit uses literal paths; reject shell/unit metacharacters.
case "$prefix" in
    *[!a-zA-Z0-9_./-]*) echo 'Prefix may contain only letters, numbers, / . _ and -.' >&2; exit 2 ;;
esac
case "$origin" in
    https://*) ;;
    *) echo 'A public HTTPS origin is required.' >&2; exit 2 ;;
esac
case "$origin" in
    *[!a-zA-Z0-9:./_-]*) echo 'Origin contains unsupported characters.' >&2; exit 2 ;;
esac
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
source_dir=$(CDPATH= cd -- "$script_dir/../.." && pwd)
if [ ! -f "$source_dir/pyproject.toml" ]; then
    echo 'Run this installer from a complete ThreadDesk source checkout.' >&2
    exit 2
fi
if [ -e "$prefix/venv" ]; then
    echo 'The target already contains a venv; retain it and choose a new installation prefix.' >&2
    exit 2
fi
mkdir -p "$prefix/data"
chmod 700 "$prefix" "$prefix/data"
python3 -m venv "$prefix/venv"
"$prefix/venv/bin/python" -m pip install "$source_dir[server]"

# Keep this generated file outside systemd's active config until reviewed.
cat > "$prefix/threaddesk-server.service" <<EOF
[Unit]
Description=ThreadDesk Server & Sync
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
UMask=0077
ExecStart=$prefix/venv/bin/threaddesk-server serve --data-dir $prefix/data --host 127.0.0.1 --port 8766 --public-origin $origin
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=default.target
EOF
echo "Installed into $prefix"
echo "Review $prefix/threaddesk-server.service before installing it as a user service."
echo 'No account initialized and no service started. See docs/SERVER-SYNC.md.'
