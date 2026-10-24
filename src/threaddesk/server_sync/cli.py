"""Provision and serve without desktop/Mac dependencies."""
from __future__ import annotations

import argparse
import ipaddress
import sys
from pathlib import Path

from threaddesk.server_sync.auth import provision
from threaddesk.server_sync.backup import backup, restore, server_lock


def main(argv=None):
    parser = argparse.ArgumentParser(prog="threaddesk-server")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Create user; print access token once")
    init.add_argument("--data-dir", type=Path, required=True)
    init.add_argument("--user", required=True)
    backup_cmd = commands.add_parser('backup',help='Create complete cold server snapshot')
    backup_cmd.add_argument('--data-dir',type=Path,required=True)
    backup_cmd.add_argument('--output',type=Path,required=True)
    restore_cmd = commands.add_parser('restore',help='Validate and restore into a NEW directory')
    restore_cmd.add_argument('--archive',type=Path,required=True)
    restore_cmd.add_argument('--data-dir',type=Path,required=True)
    serve = commands.add_parser("serve", help="Run private server behind TLS proxy")
    serve.add_argument("--data-dir", type=Path, required=True)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8766)
    serve.add_argument("--public-origin", required=True)
    serve.add_argument("--allow-http-loopback", action="store_true")
    serve.add_argument("--trusted-proxy", default="127.0.0.1", help="IP or CIDR of TLS reverse proxy; never '*'")
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            with server_lock(args.data_dir):
                print(provision(args.data_dir, args.user))
            return 0
        if args.command == 'backup':
            import json
            print(json.dumps(backup(args.data_dir,args.output)))
            return 0
        if args.command == 'restore':
            import json
            print(json.dumps(restore(args.archive,args.data_dir)))
            return 0
        ipaddress.ip_network(args.trusted_proxy, strict=False)
        if args.allow_http_loopback and args.host not in {"127.0.0.1", "::1", "localhost"}:
            parser.error("HTTP development mode must bind loopback")
        from threaddesk.server_sync.app import create_app
        import uvicorn
        app = create_app(args.data_dir, public_origin=args.public_origin, allow_http_loopback=args.allow_http_loopback)
        uvicorn.run(app, host=args.host, port=args.port, workers=1, proxy_headers=True,
                    forwarded_allow_ips=args.trusted_proxy, access_log=False, timeout_graceful_shutdown=10)
        return 0
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
