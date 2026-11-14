"""Static check that the N900 agent only uses Python 2.5 syntax and stdlib.

The N900 runs Python 2.5 (Maemo 5) and no 2.5 interpreter exists on a laptop,
so this walks the Python 3 AST of every file in n900/ (they must parse on 3
too) and flags what 2.5 cannot run: syntax added in 2.6+/3.x and stdlib
modules or functions that 2.5 lacks. If parso 0.7 is importable it also
parses each file with its Python 2.7 grammar (catches print statements and
other things the Python 3 parse cannot see).

    python3 -m pytest -q tests/test_py25_compat.py
"""
import ast
import glob
import io
import os
import tokenize

HERE = os.path.dirname(os.path.abspath(__file__))
N900 = os.path.join(HERE, '..', 'n900')
FILES = sorted(glob.glob(os.path.join(N900, '*.py')))

# modules missing from Python 2.5 (2.6+ or 3.x only). A guarded import inside
# try/except ImportError is allowed (compat.py falls back to simplejson).
NEW_MODULES = {'json', 'ssl', 'io', 'abc', 'fractions', 'multiprocessing', 'numbers',
               'queue', 'importlib', 'argparse', 'concurrent', 'asyncio', 'pathlib',
               'enum', 'typing', 'dataclasses', 'selectors', 'http', 'urllib.request',
               'html', 'configparser', 'socketserver', 'reprlib', 'builtins', 'future_builtins'}
NEW_NAMES = {
    ('collections', 'namedtuple'), ('collections', 'OrderedDict'), ('collections', 'Counter'),
    ('itertools', 'product'), ('itertools', 'permutations'), ('itertools', 'combinations'),
    ('itertools', 'chain.from_iterable'), ('itertools', 'izip_longest'),
    ('itertools', 'zip_longest'), ('itertools', 'accumulate'),
    ('math', 'isnan'), ('math', 'isinf'), ('math', 'isfinite'), ('math', 'copysign'),
    ('math', 'fsum'), ('math', 'factorial'), ('math', 'trunc'), ('math', 'gcd'),
    ('socket', 'create_connection'), ('sys', 'maxsize'), ('sys', 'float_info'),
    ('time', 'monotonic'), ('time', 'perf_counter'), ('os', 'replace'),
    ('functools', 'partialmethod'), ('functools', 'lru_cache'), ('subprocess', 'check_output'),
    ('subprocess', 'DEVNULL'), ('threading', 'get_ident'), ('string', 'Formatter'),
}
# builtins and methods added after 2.5
NEW_BUILTINS = {'bytearray', 'bytes', 'next', 'bin', 'format', 'memoryview', 'print',
                'ascii', 'exec'}
NEW_METHODS = {'format', 'is_alive', 'terminate', 'kill', 'send_signal', 'tobytes',
               'frombytes', 'to_bytes', 'from_bytes', 'isdisjoint', 'setter', 'deleter',
               'bit_length', 'casefold', 'format_map'}
# method names guarded at runtime with hasattr() in the code are fine
GUARDED_OK = {'tobytes'}


def _guarded_by_importerror(node, parents):
    p = parents.get(node)
    while p is not None:
        if isinstance(p, ast.Try):
            for h in p.handlers:
                names = []
                if isinstance(h.type, ast.Name):
                    names = [h.type.id]
                elif isinstance(h.type, ast.Tuple):
                    names = [e.id for e in h.type.elts if isinstance(e, ast.Name)]
                if 'ImportError' in names:
                    return True
        p = parents.get(p)
    return False


def problems_in(src, name='<src>'):
    out = []
    tree = ast.parse(src, name)
    parents = {}
    for node in ast.walk(tree):
        for ch in ast.iter_child_nodes(node):
            parents[ch] = node
    future = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == '__future__':
            future.update(a.name for a in node.names)

    def bad(node, what):
        out.append('%s:%d: %s' % (name, getattr(node, 'lineno', 0), what))

    for node in ast.walk(tree):
        if isinstance(node, (ast.With,)) and 'with_statement' not in future:
            bad(node, '`with` needs from __future__ import with_statement in 2.5')
        if isinstance(node, ast.With) and len(node.items) > 1:
            bad(node, '`with a, b` is 2.7+')
        if isinstance(node, ast.ExceptHandler) and node.name:
            bad(node, '`except X as e` is 2.6+ (use compat.exc())')
        if isinstance(node, ast.Constant) and isinstance(node.value, bytes):
            bad(node, "b'' literal is 2.6+ (use compat.to_bytes)")
        if isinstance(node, (ast.Set, ast.SetComp, ast.DictComp)):
            bad(node, 'set literal / set or dict comprehension is 2.7+')
        if isinstance(node, (ast.Nonlocal, ast.AsyncFunctionDef, ast.AsyncFor, ast.AsyncWith,
                             ast.Await, ast.YieldFrom, ast.JoinedStr, ast.NamedExpr,
                             ast.AnnAssign, ast.Starred)):
            bad(node, '%s is Python 3 only' % type(node).__name__)
        if isinstance(node, ast.arguments):
            if node.kwonlyargs or getattr(node, 'posonlyargs', None):
                bad(node, 'keyword-only / positional-only args are Python 3 only')
            for a in node.args + node.kwonlyargs:
                if a.annotation is not None:
                    bad(node, 'annotations are Python 3 only')
        if isinstance(node, (ast.FunctionDef,)) and node.returns is not None:
            bad(node, 'return annotation is Python 3 only')
        if isinstance(node, ast.ClassDef):
            if node.decorator_list:
                bad(node, 'class decorators are 2.6+')
            if node.keywords:
                bad(node, 'class keywords (metaclass=) are Python 3 only')
        if isinstance(node, ast.Call) and node.keywords:
            for k in node.keywords:
                if k.arg is None and any(isinstance(a, ast.Starred) for a in node.args):
                    pass
            # f(*args, kw=1) after *args is 2.6+
            star_seen = any(isinstance(a, ast.Starred) for a in node.args)
            if star_seen and any(k.arg is not None for k in node.keywords):
                bad(node, 'keyword argument after *args is 2.6+')
        if isinstance(node, ast.Import):
            for a in node.names:
                top = a.name
                if (top in NEW_MODULES or top.split('.')[0] in NEW_MODULES) and \
                        not _guarded_by_importerror(node, parents):
                    bad(node, 'module %s does not exist in 2.5' % top)
        if isinstance(node, ast.ImportFrom) and node.module and node.module != '__future__':
            if node.module in NEW_MODULES and not _guarded_by_importerror(node, parents):
                bad(node, 'module %s does not exist in 2.5' % node.module)
            for a in node.names:
                if (node.module, a.name) in NEW_NAMES:
                    bad(node, '%s.%s is 2.6+' % (node.module, a.name))
        if isinstance(node, ast.ImportFrom) and node.module == '__future__':
            for a in node.names:
                if a.name in ('print_function', 'unicode_literals'):
                    bad(node, 'from __future__ import %s is 2.6+' % a.name)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if (node.value.id, node.attr) in NEW_NAMES:
                bad(node, '%s.%s is 2.6+' % (node.value.id, node.attr))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in NEW_BUILTINS:
                if node.func.id == 'print' and len(node.args) <= 1 and not node.keywords:
                    pass  # print(x) is a valid 2.5 print statement
                elif node.func.id == 'bytes' and _in_py3_branch(node, parents):
                    pass
                else:
                    bad(node, 'builtin %s() is 2.6+/3' % node.func.id)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            recv = node.func.value
            if isinstance(recv, ast.Name) and recv.id == 'os':
                pass  # os.kill() is fine (it is Popen.kill() that is 2.6+)
            elif node.func.attr in NEW_METHODS and node.func.attr not in GUARDED_OK:
                bad(node, '.%s() is 2.6+' % node.func.attr)
        if isinstance(node, ast.Attribute) and node.attr == 'daemon' and \
                isinstance(parents.get(node), ast.Assign):
            bad(node, 'Thread.daemon is 2.6+ (use setDaemon)')
    # numeric literals 0o17 / 0b101 are 2.6+
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.NUMBER and tok.string[:2].lower() in ('0o', '0b'):
            out.append('%s:%d: %s literal is 2.6+' % (name, tok.start[0], tok.string))
        if tok.type == tokenize.NUMBER and '_' in tok.string:
            out.append('%s:%d: underscore in number is 3.6+' % (name, tok.start[0]))
    return out


def _in_py3_branch(node, parents):
    """`bytes(...)` is fine inside `if PY3:` (never runs on the N900)."""
    p = parents.get(node)
    while p is not None:
        if isinstance(p, ast.If) and isinstance(p.test, ast.Name) and p.test.id == 'PY3':
            return True
        p = parents.get(p)
    return False


def test_files_exist():
    names = [os.path.basename(f) for f in FILES]
    for n in ('agent.py', 'transport.py', 'sensors.py', 'capture.py', 'compat.py',
              'screens.py', 'ui.py'):
        assert n in names


def test_no_post_25_constructs():
    found = []
    for f in FILES:
        found += problems_in(open(f).read(), os.path.basename(f))
    assert not found, '\n'.join(found)


def test_checker_catches_known_bad_code():
    samples = [
        "try:\n    pass\nexcept ValueError as e:\n    pass\n",
        "x = b'abc'\n",
        "s = '{}'.format(1)\n",
        "with open('f') as f:\n    pass\n",
        "import json\n",
        "from collections import namedtuple\n",
        "x = {1, 2}\n",
        "d = {k: 1 for k in 'ab'}\n",
        "def f(*, a):\n    pass\n",
        "def f():\n    nonlocal x\n",
        "print('a', 'b', end='')\n",
        "import math\nmath.isnan(1.0)\n",
        "x = 0o17\n",
        "y = next(iter([1]))\n",
    ]
    for s in samples:
        assert problems_in(s), 'not caught: %r' % s
    ok = [
        "from __future__ import with_statement\nwith open('f') as f:\n    pass\n",
        "try:\n    import json\nexcept ImportError:\n    json = None\n",
        "x = 1 if True else 2\n",
        "try:\n    pass\nexcept ValueError:\n    pass\nfinally:\n    pass\n",
        "print('one')\n",
    ]
    for s in ok:
        assert not problems_in(s), 'false positive: %r %s' % (s, problems_in(s))


def test_python27_grammar_if_parso_available():
    """Parse with parso's Python 2.7 grammar (pip install parso==0.7.1)."""
    try:
        import parso
        g = parso.load_grammar(version='2.7')
    except Exception:
        import pytest
        pytest.skip('parso 0.7 with a Python 2.7 grammar is not installed')
    errs = []
    for f in FILES:
        src = open(f).read()
        mod = g.parse(src)
        for e in g.iter_errors(mod):
            line = src.splitlines()[e.start_pos[0] - 1].strip()
            if line.startswith('del ') and 'starred' in e.message:
                continue  # parso 0.7 bug: flags the valid `del a, b`
            errs.append('%s:%d: %s' % (os.path.basename(f), e.start_pos[0], e.message))
    assert not errs, '\n'.join(errs)
