import os

import pytest

from litmus.compat import prepare, py2_to_py3
from litmus.sandbox import Sandbox, outputs_match


@pytest.fixture(scope="module")
def sb():
    s = Sandbox(case_timeout=1.0, max_workers=2)
    yield s
    s.close()


def test_output_comparison():
    assert outputs_match("YES\r\n", "yes")
    assert outputs_match("1 2\n3", "1  2 3")
    assert outputs_match("0.3333333", "0.33333333")
    assert not outputs_match("1 2", "1 3")


def test_compat_variants():
    assert prepare("print(1)")[1] == "as_is"
    assert prepare("x = 1\nreturn\n")[1] == "wrapped"
    assert prepare("print 'hi'")[1] == "py2"
    assert "print(x, end=' ')" in py2_to_py3("print x,")


def test_stdin_idioms(sb):
    r = sb.run("import sys\nn=int(input())\nprint(n*2)\nprint(sum(map(int,sys.stdin.read().split())))", ["4\n1 2 3\n"])
    assert r[0].status == "ok" and r[0].stdout.split() == ["8", "6"]
    r = sb.run("N,*A=map(int,open(0).read().split())\nprint(sum(A))", ["3 1 2 3\n"])
    assert r[0].stdout.strip() == "6"


def test_timeout_and_isolation(sb, tmp_path):
    assert sb.run("while True: pass", ["1\n"])[0].status == "timeout"
    assert sb.run("import os\nos.system('echo hi')", ["1\n"])[0].status == "blocked"
    target = os.path.join(str(tmp_path), "x.txt")
    r = sb.run("open(%r,'w').write('x')" % target, ["\n"])
    assert r[0].status == "blocked" and not os.path.exists(target)


def test_fresh_namespace_per_case(sb):
    r = sb.run("try:\n    seen\n    print('leak')\nexcept NameError:\n    seen=1\n    print('fresh')", ["\n", "\n"])
    assert [c.stdout.strip() for c in r] == ["fresh", "fresh"]
