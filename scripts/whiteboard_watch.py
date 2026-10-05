#!/usr/bin/env python3
"""Read a local ThreadDesk JSON whiteboard on a macOS launchd timer.

This is a file reader, not a model runner or an acknowledgement by an AI.
Uses only the Python standard library; compatible with Python 3.8+.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.chmod(str(temporary), 0o600)
    temporary.replace(path)


def write_wake_log(path, items, observed_at, thread_id):
    """Commit an idempotent metadata journal before advancing the read cursor.

    Atomic replacement means monitors must watch the parent directory or reopen
    the pathname. A saved journal also recovers a crash before status.json saves.
    """
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []
    known = set()
    for row in rows:
        if row.get('thread_id') != thread_id or not isinstance(row.get('entry_id'), str):
            raise ValueError('Invalid wake journal identity')
        if row['entry_id'] in known:
            raise ValueError('Duplicate wake journal identity')
        known.add(row['entry_id'])
    additions = [dict(thread_id=thread_id, entry_id=item['id'], ordinal=item.get('ordinal'),
                      actor=item.get('actor'), observed_at=observed_at)
                 for item in items if item['id'] not in known]
    if not additions:
        return 0
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        os.chmod(str(temporary), 0o600)
        for row in rows + additions:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    return len(additions)


def notify():
    # Fixed text: whiteboard content is never interpolated into executable code.
    result = subprocess.run([
        '/usr/bin/osascript', '-l', 'JavaScript', '-e',
        'var app = Application.currentApplication(); app.includeStandardAdditions = true; '
        'app.displayNotification("Neue Whiteboard-Einträge: bitte im ThreadDesk lesen.", '
        '{withTitle: "ThreadDesk · 5-Minuten-Wecker"});'
    ], capture_output=True, text=True, timeout=15)
    return 'submitted' if result.returncode == 0 else 'failed'


def tick(root, thread_id, state_path, notifications=False):
    root, state_path = Path(root), Path(state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with state_path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
        identity = {'root': str(root.resolve()), 'thread_id': thread_id}
        if state and any(state.get(k) != v for k, v in identity.items()):
            raise ValueError('State belongs to another whiteboard')
        attempted = now()
        try:
            thread = json.loads((root / 'threads' / (thread_id + '.json')).read_text(encoding='utf-8'))
            if thread.get('id') != thread_id:
                raise ValueError('Wrong thread identity')
            directory = root / 'whiteboard' / thread_id
            if not directory.is_dir():
                raise ValueError('Whiteboard directory is missing')
            entries = {}
            metadata = {}
            for path in sorted(directory.glob('*.json')):
                item = json.loads(path.read_text(encoding='utf-8'))
                entry_id = item.get('id')
                if not isinstance(entry_id, str) or not entry_id or item.get('thread_id') != thread_id:
                    raise ValueError('Invalid whiteboard entry: ' + path.name)
                if not isinstance(item.get('content'), str):
                    raise ValueError('Missing entry content: ' + path.name)
                if entry_id in entries:
                    raise ValueError('Duplicate entry ID: ' + entry_id)
                digest = hashlib.sha256(json.dumps(item, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()
                entries[entry_id] = digest
                metadata[entry_id] = item
        except (OSError, ValueError) as exc:
            state.update(identity)
            state.update(last_attempt_at=attempted, status='error', error=str(exc))
            atomic_json(state_path, state)
            return state
        old = state.get('seen', {})
        fresh = sorted(set(entries) - set(old))
        wake_path = state_path.parent / 'wake.log'
        try:
            emitted = write_wake_log(wake_path, [metadata[key] for key in fresh], attempted, thread_id)
        except (OSError, ValueError) as exc:
            state.update(identity)
            state.update(last_attempt_at=attempted, status='error', error='wake.log: ' + str(exc))
            atomic_json(state_path, state)
            return state
        changed = sorted(key for key in entries if key in old and entries[key] != old[key])
        missing = sorted(set(old) - set(entries))
        # Keep known IDs even if temporarily removed; reappearance is not a new entry.
        seen = dict(old)
        seen.update(entries)
        pending = sorted(set(state.get('pending_notice_ids', [])) | set(fresh) | set(changed))
        state.update(identity)
        state.update(
            status='ok', error=None, last_attempt_at=attempted,
            previous_success_at=state.get('last_success_at'), last_success_at=now(),
            successful_reads=state.get('successful_reads', 0) + 1,
            entry_count=len(entries), new_ids=fresh, changed_ids=changed, missing_ids=missing,
            pending_notice_ids=pending, seen=seen,
            agent_delivery='not_connected', notification='disabled', interval_seconds=300,
            wake_log=str(wake_path), wake_events_written=emitted,
        )
        if notifications and pending:
            try:
                state['notification'] = notify()
            except (OSError, subprocess.TimeoutExpired):
                state['notification'] = 'failed'
            if state['notification'] == 'submitted':
                state['pending_notice_ids'] = []
        elif notifications:
            state['notification'] = 'no_new_entries'
        atomic_json(state_path, state)
        return state


def paths(thread_id):
    folder = Path.home() / 'Library' / 'Application Support' / 'ThreadDesk' / 'whiteboard-watch' / thread_id
    label = 'de.netzwerkpunkt.threaddesk.whiteboard.' + thread_id
    plist = Path.home() / 'Library' / 'LaunchAgents' / (label + '.plist')
    return folder, label, plist


def install(root, thread_id):
    if sys.platform != 'darwin':
        raise ValueError('Installation requires macOS launchd')
    root = root.resolve()
    # Validate before installing anything persistent.
    thread = json.loads((root / 'threads' / (thread_id + '.json')).read_text(encoding='utf-8'))
    if thread.get('id') != thread_id or not (root / 'whiteboard' / thread_id).is_dir():
        raise ValueError('Whiteboard is missing or belongs to another thread')
    folder, label, plist = paths(thread_id)
    if plist.exists():
        raise ValueError('Timer already installed; inspect status or uninstall first')
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(str(folder), 0o700)
    script = folder / 'whiteboard_watch.py'
    shutil.copy2(str(Path(__file__).resolve()), str(script))
    program = [str(Path(sys.executable).resolve()), str(script), 'once', '--root', str(root),
               '--thread', thread_id, '--state', str(folder / 'status.json'), '--notify']
    config = {'Label': label, 'ProgramArguments': program, 'StartInterval': 300,
              'RunAtLoad': True, 'ProcessType': 'Background', 'Umask': 63}
    plist.parent.mkdir(parents=True, exist_ok=True)
    with plist.open('xb') as stream:
        plistlib.dump(config, stream)
    os.chmod(str(plist), 0o600)
    result = subprocess.run(['/bin/launchctl', 'bootstrap', 'gui/' + str(os.getuid()), str(plist)],
                            capture_output=True, text=True)
    if result.returncode:
        plist.unlink()
        raise RuntimeError('launchd registration failed: ' + result.stderr.strip())
    return {'installed': True, 'label': label, 'interval_seconds': 300,
            'status_file': str(folder / 'status.json'), 'agent_delivery': 'not_connected'}


def uninstall(thread_id):
    folder, label, plist = paths(thread_id)
    target = 'gui/{}/{}'.format(os.getuid(), label)
    registered = subprocess.run(['/bin/launchctl', 'print', target], capture_output=True).returncode == 0
    if registered:
        subprocess.run(['/bin/launchctl', 'bootout', target], check=True)
    if plist.exists():
        plist.unlink()
    return {'installed': False, 'status_preserved': str(folder / 'status.json')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['once', 'status', 'install', 'uninstall'])
    parser.add_argument('--root', type=Path, default=Path.home() / '.threaddesk')
    parser.add_argument('--thread', required=True)
    parser.add_argument('--state', type=Path)
    parser.add_argument('--notify', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', args.thread):
        parser.error('Invalid thread ID')
    status_file = args.state or paths(args.thread)[0] / 'status.json'
    if args.action == 'install':
        result = install(args.root, args.thread)
    elif args.action == 'uninstall':
        result = uninstall(args.thread)
    elif args.action == 'status':
        result = json.loads(status_file.read_text(encoding='utf-8'))
    else:
        result = tick(args.root, args.thread, status_file, args.notify)
    # Content and hashes remain local; concise output carries only timing and counts.
    print(json.dumps({k: v for k, v in result.items() if k != 'seen'}, ensure_ascii=False, indent=2))
    return 1 if result.get('status') == 'error' else 0


if __name__ == '__main__':
    sys.exit(main())
