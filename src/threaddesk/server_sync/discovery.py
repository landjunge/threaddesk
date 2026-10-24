"""Static, bounded project inventory with explicit local authority boundaries.

Never executes imports, package managers or project code. A local grant is a file
or directory chosen by the owner. A remote/server reference is only a request to
check an existing grant, never authority to read another host path.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import stat
import sys
import unicodedata
from urllib.parse import unquote, urlsplit

from threaddesk.server_sync.store import MAX_FILE_BYTES, SyncError, validate_path

MAX_FILES = 20000
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_PARSE_BYTES = 2 * 1024 * 1024
MAX_GRANTS = 128
VCS = {'.git', '.hg', '.svn'}
MANAGED = '.threaddesk-sync-conflicts'
JS_EXTENSIONS = ('.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx', '.json')
_NODE_BUILTINS = {'assert', 'async_hooks', 'buffer', 'child_process', 'cluster', 'console', 'constants', 'crypto', 'dgram', 'diagnostics_channel', 'dns', 'domain', 'events', 'fs', 'http', 'http2', 'https', 'inspector', 'module', 'net', 'os', 'path', 'perf_hooks', 'process', 'punycode', 'querystring', 'readline', 'repl', 'stream', 'string_decoder', 'sys', 'test', 'timers', 'tls', 'trace_events', 'tty', 'url', 'util', 'v8', 'vm', 'wasi', 'worker_threads', 'zlib'}
MD_LINK = re.compile(r'(!?)\[[^\]]*\]\(\s*<?([^\s)>]+)')
CSS_LINK = re.compile(r'''url\(\s*["']?([^\s'"\)]+)|@import\s*["']([^"']+)["']''', re.I)
JS_IMPORT = re.compile(r'''(?:\b(?:import|export)\s+(?:[^;\n]*?\s+from\s+)?["']([^"']+)["']|\b(?:require|import)\s*\(\s*["']([^"']+)["']\s*\))''')
JS_DYNAMIC = re.compile(r'\b(?:require|import)\s*\(\s*(?![\s"\'])[^\s)]')
JS_ASSET = re.compile(r'''(?:new\s+URL|\bfetch|\b(?:readFile|readFileSync))\s*\(\s*["']([^"']+)["']''')
_STDLIB = set(getattr(sys, 'stdlib_module_names', ())) | set(sys.builtin_module_names) | {'os', 'sys', 'pathlib', 'json', 'typing', 'dataclasses', 'hashlib', 're', 'math', 'collections', 'datetime', 'urllib', 'unittest', 'asyncio'}


class DiscoveryError(ValueError):
    pass


def _safe(value):
    try:
        validate_path(value)
        return True
    except (SyncError, UnicodeError):
        return False


def _absolute(value, parent=None):
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (parent or Path.cwd()) / path
    # Normalize dot segments lexically; do NOT resolve symlinks.
    return Path(os.path.abspath(path))


def _directory_fd(path):
    descriptor = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in Path(path).parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


@dataclass(frozen=True)
class SourceFile:
    root: Path
    relative: str

    @property
    def path(self):
        return self.root / self.relative

    def read_bytes(self):
        """Read only the mapped file through descriptor-bound nonsymlink ancestors."""
        if not _safe(self.relative):
            raise DiscoveryError('Unsafe source path')
        parent = _directory_fd(self.root)
        try:
            parts = self.relative.split('/')
            for part in parts[:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                os.close(parent)
                parent = child
            descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            with os.fdopen(descriptor, 'rb') as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE_BYTES:
                    raise DiscoveryError('Unsupported or oversized source file')
                data = stream.read(MAX_FILE_BYTES + 1)
                after = os.fstat(stream.fileno())
                if len(data) > MAX_FILE_BYTES or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise DiscoveryError('Source changed during inventory')
                return data
        finally:
            os.close(parent)


@dataclass
class DiscoveryPlan:
    files: list[dict] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    sources: dict[str, SourceFile] = field(default_factory=dict)
    limitations: tuple[str, ...] = ('Static analysis cannot prove completeness of arbitrary runtime-generated dependencies.',)

    @property
    def mapping(self):
        return self.sources


@dataclass(frozen=True)
class _Grant:
    path: Path
    directory: bool
    prefix: str

    def relative(self, target):
        if self.directory:
            try:
                return target.relative_to(self.path).as_posix()
            except ValueError:
                return None
        return target.name if target == self.path else None

    @property
    def root(self):
        return self.path if self.directory else self.path.parent


class _HTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.references = []
        self.inline_css = []
        self.inline_js = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag in {'style', 'script'}:
            self.current = tag
        for key in ('src', 'poster', 'data'):
            if values.get(key):
                self.references.append((values[key], True))
        if values.get('href'):
            self.references.append((values['href'], tag in {'link', 'use'}))
        if values.get('srcset'):
            self.references.extend((item.strip().split()[0], True) for item in values['srcset'].split(',') if item.strip())
        if values.get('style'):
            for match in CSS_LINK.finditer(values['style']):
                self.references.append((next(v for v in match.groups() if v), True))
        if tag == 'base' and values.get('href'):
            self.references.append(('__dynamic_html_base__', True))

    def handle_endtag(self, tag):
        if tag == self.current:
            self.current = None

    def handle_data(self, data):
        if self.current == 'style':
            self.inline_css.append(data)
        elif self.current == 'script':
            self.inline_js.append(data)


def _literal(node, source):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name) and node.id == '__file__':
        return str(source)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Div)):
        left, right = _literal(node.left, source), _literal(node.right, source)
        if left is not None and right is not None:
            return left + right if isinstance(node.op, ast.Add) else str(Path(left) / right)
    if isinstance(node, ast.Attribute) and node.attr == 'parent':
        value = _literal(node.value, source)
        return str(Path(value).parent) if value is not None else None
    if isinstance(node, ast.Call):
        name = _call_name(node.func)
        values = [_literal(value, source) for value in node.args]
        if name in {'Path', 'pathlib.Path', 'os.path.join'} and values and all(v is not None for v in values):
            return str(Path(values[0]).joinpath(*values[1:]))
        if isinstance(node.func, ast.Attribute) and node.func.attr in {'with_name', 'with_suffix'} and len(values) == 1 and values[0] is not None:
            base = _literal(node.func.value, source)
            if base is not None:
                try:
                    return str(getattr(Path(base), node.func.attr)(values[0]))
                except ValueError:
                    return None
    return None


def _call_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _call_name(node.value) + '.' + node.attr
    return ''


class _Inventory:
    def __init__(self, root):
        self.root = _absolute(root)
        self.plan = DiscoveryPlan()
        self.grants = []
        self.data = {}
        self.physical = {}
        self.total = 0
        self.directories = 0
        self.path_aliases = {}
        self.file_keys = set()
        self.directory_keys = set()

    def issue(self, message, logical=None):
        value = ((logical + ': ' if logical else '') + message).encode('utf-8', errors='backslashreplace').decode('utf-8')[:1900]
        if len(self.plan.issues) < 1999:
            self.plan.issues.append(value)
        elif len(self.plan.issues) == 1999:
            self.plan.issues.append('Additional inventory issues omitted; project remains blocked.')

    def add_grant(self, value, *, primary=False, label=None):
        if len(self.grants) >= MAX_GRANTS:
            self.issue('Too many explicitly approved roots')
            return
        target = _absolute(value, self.root)
        try:
            if any(part.casefold() in {'.ssh', '.aws', '.gnupg', '.git', '.hg', '.svn'} for part in target.parts):
                raise DiscoveryError('Forbidden source ancestry')
            parent = _directory_fd(target.parent)
            try:
                info = os.stat(target.name, dir_fd=parent, follow_symlinks=False)
            finally:
                os.close(parent)
            if stat.S_ISLNK(info.st_mode) or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                raise DiscoveryError('Unsafe root type')
            if not primary:
                # A grant to a secret directory/file is not an override of policy.
                if not _safe(target.name):
                    raise DiscoveryError('Approved root violates path policy')
            if primary and not stat.S_ISDIR(info.st_mode):
                raise DiscoveryError('Selected project must be a directory')
        except (OSError, DiscoveryError):
            self.issue('Approved source is missing, unsafe or unreadable' if not primary else 'Selected project root is unavailable or unsafe')
            return
        if any(g.path == target for g in self.grants):
            return
        if primary:
            prefix = ''
        else:
            slug = re.sub(r'[^A-Za-z0-9_-]+', '-', label or target.name).strip('-')[:40] or 'source'
            prefix = '_external/' + slug + '-' + hashlib.sha256(str(target).encode()).hexdigest()[:12]
        grant = _Grant(target, stat.S_ISDIR(info.st_mode), prefix)
        self.grants.append(grant)

    def authorized(self, target):
        # Selected root and earlier, narrower grants win deterministically.
        for grant in self.grants:
            relative = grant.relative(target)
            if relative is not None:
                return grant, relative
        return None

    def add_file(self, grant, relative):
        if len(self.plan.files) >= MAX_FILES:
            self.issue('Project exceeds inventory file limit')
            return
        logical = grant.prefix + '/' + relative if grant.prefix else relative
        if not _safe(relative) or not _safe(logical):
            self.issue('Unsafe or secret-bearing source omitted', logical)
            return
        target = grant.root / relative
        if logical in self.plan.sources and self.plan.sources[logical].path != target:
            self.issue('Duplicate logical path maps different sources', logical)
            return
        if target in self.physical:
            return
        # Prefix maps avoid an O(files²) comparison on large project trees.
        parts = logical.split('/')
        prefixes = ['/'.join(parts[:index]) for index in range(1, len(parts) + 1)]
        keys = [unicodedata.normalize('NFC', value).casefold() for value in prefixes]
        for index, (prefix, key) in enumerate(zip(prefixes, keys)):
            if key in self.path_aliases and self.path_aliases[key] != prefix:
                self.issue('Case/Unicode path collision; omitted', logical)
                return
            if index < len(keys) - 1 and key in self.file_keys:
                self.issue('File/directory path collision; omitted', logical)
                return
        if keys[-1] in self.directory_keys:
            self.issue('File/directory path collision; omitted', logical)
            return
        source = SourceFile(grant.root, relative)
        try:
            data = source.read_bytes()
            if self.total + len(data) > MAX_TOTAL_BYTES:
                self.issue('Project exceeds inventory byte limit')
                return
        except (OSError, DiscoveryError):
            self.issue('File is unavailable, unsafe, changed or exceeds file limit', logical)
            return
        self.total += len(data)
        self.path_aliases.update(zip(keys, prefixes))
        self.file_keys.add(keys[-1])
        self.directory_keys.update(keys[:-1])
        self.plan.files.append({'path': logical, 'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)})
        self.plan.sources[logical] = source
        self.physical[target] = logical
        parsable = target.suffix.lower() in {'.py', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx', '.html', '.htm', '.css', '.md', '.markdown', '.json', '.webmanifest'}
        if parsable and len(data) <= MAX_PARSE_BYTES:
            self.data[logical] = data
        elif parsable:
            self.issue('Source exceeds static dependency parser limit', logical)

    def scan(self):
        for grant in self.grants:
            if not grant.directory:
                self.add_file(grant, grant.path.name)
                continue
            for parent, directories, names in os.walk(grant.path, followlinks=False,
                    onerror=lambda exc: self.issue('Unreadable approved directory')):
                self.directories += 1
                if self.directories > MAX_FILES:
                    self.issue('Project exceeds directory inventory limit')
                    return
                prefix = Path(parent).relative_to(grant.path)
                for name in list(directories):
                    path = Path(parent) / name
                    relative = (prefix / name).as_posix()
                    if name == MANAGED or (name.casefold() in VCS and not path.is_symlink()):
                        directories.remove(name)
                    elif path.is_symlink() or not _safe(relative):
                        directories.remove(name)
                        self.issue('Unsafe or secret-bearing directory omitted', relative)
                for name in names:
                    path = Path(parent) / name
                    if name.casefold() in VCS and not path.is_symlink():
                        continue
                    if re.fullmatch(r'\.td-sync-[a-f0-9]{32}', name):
                        continue
                    self.add_file(grant, (prefix / name).as_posix())
                    if len(self.plan.files) >= MAX_FILES:
                        self.issue('Project exceeds inventory file limit')
                        return

    def reference(self, value, logical, *, base=None, required_remote=False, js=False, web=False):
        if not isinstance(value, str) or not value:
            self.issue('Unresolved dynamic dependency', logical)
            return
        if value in self.plan.sources:
            return
        try:
            parsed = urlsplit(value)
        except ValueError:
            self.issue('Malformed dependency reference', logical)
            return
        if parsed.scheme in {'http', 'https', 'data', 'mailto', 'tel', 'javascript'} or parsed.netloc:
            if required_remote and parsed.scheme not in {'data'}:
                self.issue('Remote dependency is unavailable without network', logical)
            return
        if parsed.scheme not in {'', 'file'}:
            self.issue('Unsupported dependency URI scheme', logical)
            return
        if not parsed.path:
            return
        if value == '__dynamic_html_base__':
            self.issue('HTML base URL requires an explicit dependency mapping', logical)
            return
        raw_path = unquote(parsed.path)
        if web and raw_path.startswith('/') and parsed.scheme != 'file':
            target = _absolute(raw_path.lstrip('/'), self.root)
        else:
            target = _absolute(raw_path, base or self.plan.sources[logical].path.parent)
        candidates = [target]
        if js and not target.suffix:
            candidates.extend(Path(str(target) + ext) for ext in JS_EXTENSIONS)
            candidates.extend(target / ('index' + ext) for ext in JS_EXTENSIONS)
        allowed = [(candidate, self.authorized(candidate)) for candidate in candidates]
        for candidate, authority in allowed:
            if authority is None:
                continue
            grant, relative = authority
            if relative == '.':
                return  # Explicitly approved directory root.
            if not _safe(relative):
                self.issue('Dependency violates path policy', logical)
                return
            # Data was obtained through bound descriptors; never trust exists()/resolve().
            if candidate in self.physical:
                return
            try:
                parent = _directory_fd(candidate.parent)
                try:
                    info = os.stat(candidate.name, dir_fd=parent, follow_symlinks=False)
                finally:
                    os.close(parent)
                if stat.S_ISDIR(info.st_mode) and grant.directory:
                    return
            except OSError:
                pass
        self.issue('Missing, unsafe or unapproved dependency', logical)

    def python_import(self, module, logical, *, level=0):
        source = self.plan.sources[logical].path
        if not level and module.split('.')[0] in _STDLIB:
            return
        if level:
            parent = source.parent
            for _ in range(level - 1):
                parent = parent.parent
            candidates = [parent / module.replace('.', '/')]
        else:
            part = module.replace('.', '/')
            roots = [source.parent, self.root, self.root / 'src']
            roots.extend(g.root for g in self.grants)
            candidates = [root / part for root in roots]
            for grant in self.grants:
                if module.split('.')[0] == grant.root.name:
                    tail = module.split('.')[1:]
                    candidates.append(grant.root.joinpath(*tail))
        for candidate in candidates:
            for path in [candidate.with_suffix('.py'), candidate / '__init__.py']:
                if path in self.physical:
                    return
            if any(path.is_relative_to(candidate) for path in self.physical):
                return  # Namespace package within approved inventory.
        self.issue('Unresolved Python import or external environment package: ' + module, logical)

    def python(self, logical, data):
        try:
            tree = ast.parse(data, filename=logical)
        except (SyntaxError, UnicodeError, ValueError):
            self.issue('Python syntax cannot be statically inspected', logical)
            return
        source = self.plan.sources[logical].path
        aliases = {}
        for imported in ast.walk(tree):
            if isinstance(imported, ast.Import):
                for alias in imported.names:
                    if alias.asname:
                        aliases[alias.asname] = alias.name
            elif isinstance(imported, ast.ImportFrom) and imported.module:
                for alias in imported.names:
                    aliases[alias.asname or alias.name] = imported.module + '.' + alias.name
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.python_import(alias.name, logical)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    self.python_import(node.module, logical, level=node.level)
                else:
                    for alias in node.names:
                        self.python_import(alias.name, logical, level=node.level)
            elif isinstance(node, ast.Call):
                name = _call_name(node.func)
                first, separator, remainder = name.partition('.')
                name = aliases.get(first, first) + (separator + remainder if separator else '')
                if name in {'__import__', 'importlib.import_module'}:
                    value = _literal(node.args[0], source) if node.args else None
                    if value:
                        self.python_import(value, logical)
                    else:
                        self.issue('Unresolved dynamic Python import', logical)
                elif name in {'open', 'io.open', 'builtins.open'}:
                    mode = _literal(node.args[1], source) if len(node.args) > 1 else next((_literal(k.value, source) for k in node.keywords if k.arg == 'mode'), 'r')
                    if mode is not None and any(char in mode for char in 'wax'):
                        continue  # An output path is not a required input file.
                    value = _literal(node.args[0], source) if node.args else None
                    self.reference(value, logical, base=self.root)
                elif isinstance(node.func, ast.Attribute) and node.func.attr in {'read_text', 'read_bytes', 'iterdir', 'glob', 'rglob', 'open'}:
                    self.reference(_literal(node.func.value, source), logical, base=self.root)
                    if node.func.attr in {'glob', 'rglob'} and (not node.args or _literal(node.args[0], source) is None):
                        self.issue('Unresolved dynamic file glob', logical)
                elif name in {'eval', 'exec', 'os.system', 'subprocess.run', 'subprocess.Popen', 'runpy.run_path'}:
                    self.issue('Runtime execution may introduce undeclared dependencies', logical)

    def js_package(self, value, logical):
        """Find an actual provisioned package entry, never just a package folder."""
        source = self.plan.sources[logical].path
        roots = {g.root for g in self.grants}
        roots.update(parent for parent in source.parents if self.authorized(parent) is not None)
        for root in roots:
            candidate = root / 'node_modules' / value
            variants = [candidate] + [Path(str(candidate) + ext) for ext in JS_EXTENSIONS]
            variants.extend(candidate / ('index' + ext) for ext in JS_EXTENSIONS)
            if any(path in self.physical for path in variants):
                return True
            manifest = candidate / 'package.json'
            if manifest not in self.physical:
                continue
            try:
                package = json.loads(self.data[self.physical[manifest]])
            except (KeyError, ValueError, UnicodeError):
                continue
            if not isinstance(package, dict):
                continue
            entry = package.get('module') or package.get('main')
            exports = package.get('exports')
            if not entry and isinstance(exports, str):
                entry = exports
            elif not entry and isinstance(exports, dict) and isinstance(exports.get('.'), str):
                entry = exports['.']
            if isinstance(entry, str):
                self.reference(str(_absolute(entry, candidate)), logical, js=True)
                return True
            self.issue('Package exports require an explicit runtime mapping: ' + value, logical)
            return True
        return False

    def javascript(self, logical, data):
        text = data.decode('utf-8', errors='replace')
        for match in JS_IMPORT.finditer(text):
            value = next(v for v in match.groups() if v)
            package = value.removeprefix('node:').split('/')[0]
            if package in _NODE_BUILTINS and (value.startswith('node:') or not value.startswith(('.', '/'))):
                continue
            if value.startswith(('.', '/')) or urlsplit(value).scheme:
                self.reference(value, logical, js=True, required_remote=True, web=True)
            elif self.js_package(value, logical):
                continue
            else:
                self.issue('External JS package requires an explicitly provisioned environment: ' + value.split('/')[0], logical)
        if JS_DYNAMIC.search(text):
            self.issue('Unresolved dynamic JS import/require', logical)
        for match in JS_ASSET.finditer(text):
            self.reference(match.group(1), logical, required_remote=True, web=True)
        if re.search(r'\b(?:fetch|readFile|readFileSync)\s*\(\s*(?![\s"\'])[^\s)]', text):
            self.issue('Unresolved dynamic JS file/resource dependency', logical)

    def manifest(self, logical, data):
        try:
            value = json.loads(data)
        except (ValueError, UnicodeError):
            self.issue('Dependency manifest is not valid JSON', logical)
            return
        if not isinstance(value, dict):
            return
        source = self.plan.sources[logical].path
        if source.name == 'package.json':
            for key in ('main', 'module', 'types', 'typings', 'browser', 'bin', 'files', 'assets'):
                entry = value.get(key)
                paths = [entry] if isinstance(entry, str) else list(entry.values()) if isinstance(entry, dict) else entry if isinstance(entry, list) else []
                for path in paths:
                    if isinstance(path, str) and not any(c in path for c in '*?['):
                        self.reference(path, logical, js=True, web=True)
                    elif isinstance(path, str):
                        # All approved trees are already inventoried. A glob is bounded
                        # only if its literal non-glob parent stays inside a grant.
                        prefix = re.split(r'[*?\[]', path, 1)[0]
                        self.reference(str(Path(prefix).parent), logical)
            for dependency in value.get('dependencies', {}) if isinstance(value.get('dependencies', {}), dict) else []:
                if not self.js_package(dependency, logical):
                    self.issue('Missing provisioned JS package: ' + dependency, logical)
        elif source.name in {'manifest.json', 'site.webmanifest'}:
            for entry in value.get('icons', []) if isinstance(value.get('icons'), list) else []:
                if isinstance(entry, dict) and isinstance(entry.get('src'), str):
                    self.reference(entry['src'], logical, required_remote=True, web=True)
            for key in ('start_url',):
                if isinstance(value.get(key), str):
                    self.reference(value[key], logical, required_remote=True, web=True)

    def inspect(self):
        for logical, data in self.data.items():
            suffix = Path(logical).suffix.lower()
            if suffix == '.py':
                self.python(logical, data)
            elif suffix in {'.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx'}:
                self.javascript(logical, data)
            elif suffix in {'.md', '.markdown'}:
                for match in MD_LINK.finditer(data.decode('utf-8', errors='replace')):
                    self.reference(match.group(2), logical, required_remote=bool(match.group(1)), web=True)
            elif suffix in {'.html', '.htm'}:
                parser = _HTML()
                try:
                    parser.feed(data.decode('utf-8', errors='replace'))
                    for value, required in parser.references:
                        self.reference(value, logical, required_remote=required, web=True)
                    for text in parser.inline_css:
                        for match in CSS_LINK.finditer(text):
                            self.reference(next(v for v in match.groups() if v), logical, required_remote=True, web=True)
                    for text in parser.inline_js:
                        self.javascript(logical, text.encode('utf-8'))
                except (ValueError, IndexError):
                    self.issue('HTML dependencies could not be inspected', logical)
            elif suffix == '.css':
                for match in CSS_LINK.finditer(data.decode('utf-8', errors='replace')):
                    self.reference(next(v for v in match.groups() if v), logical, required_remote=True, web=True)
            elif suffix == '.json' or Path(logical).name == 'site.webmanifest':
                self.manifest(logical, data)


def discover_project(root, *, local_references=(), approved_roots=(), server_references=()):
    """Inventory selected tree and explicit owner-local grants without mutations.

    ``local_references`` may be trusted ThreadDesk context.files strings. Passing
    server-returned references here would violate the authority boundary; pass
    them via ``server_references`` instead. Approved roots can be paths or a
    mapping of display labels to paths. Relative grants resolve against root.
    """
    inventory = _Inventory(root)
    inventory.add_grant(inventory.root, primary=True)
    roots = approved_roots.items() if isinstance(approved_roots, dict) else ((None, path) for path in approved_roots)
    for label, path in roots:
        inventory.add_grant(path, label=label)
    for value in local_references:
        if not isinstance(value, (str, Path)):
            inventory.issue('Invalid local file reference')
            continue
        raw = str(value)
        parsed = urlsplit(raw)
        if parsed.scheme in {'http', 'https', 'data', 'mailto', 'tel'}:
            continue
        if parsed.scheme not in {'', 'file'} or parsed.netloc:
            inventory.issue('Unsupported local file reference')
            continue
        if parsed.path:
            inventory.add_grant(unquote(parsed.path))
    inventory.scan()
    inventory.inspect()
    # Remote references are checked only against files already read from grants.
    for value in server_references:
        if isinstance(value, str):
            # Use a synthetic existing source to carry only a logical origin label.
            if inventory.plan.sources:
                logical = next(iter(inventory.plan.sources))
                inventory.reference(value, logical, base=inventory.root)
            elif value:
                inventory.issue('Server dependency has no approved local source')
    inventory.plan.files.sort(key=lambda item: item['path'])
    inventory.plan.issues = sorted(set(inventory.plan.issues))
    return inventory.plan
