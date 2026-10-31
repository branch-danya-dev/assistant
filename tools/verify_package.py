"""Load the built wheel outside its checkout and run the offline fixture workflow."""
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    repository = Path(__file__).resolve().parents[1]
    wheels = list((repository / "dist").glob("personal_agent-*.whl"))
    if len(wheels) != 1:
        raise SystemExit("Expected one built wheel in dist/")
    parent = repository.parent / "package-checks"
    parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=parent) as temporary:
        target = Path(temporary) / "package"
        subprocess.run([sys.executable, "-m", "pip", "install", "--no-index", "--no-deps",
                        "--target", str(target), str(wheels[0])], check=True,
                       capture_output=True, text=True, timeout=60)
        program = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import personal_agent
from personal_agent.config import Paths, specification
from personal_agent.demo import run_demo
from personal_agent.previews import Previews
from personal_agent.storage import Store
assert Path(personal_agent.__file__).is_relative_to(Path(sys.argv[1]))
assert specification('model-config.json')['primary_local']['model'] == 'qwen3.5:9b'
result = run_demo(Paths(Path(sys.argv[2])))
assert result['task']['state'] == 'completed', result['task']['block_reason']
assert result['result']['verified_steps'] == 2
assert 'partial' in specification('schemas/task-state.schema.json')['properties']['state']['enum']
with Store(Paths(Path(sys.argv[2]))) as store:
    assert store.connection.execute('PRAGMA user_version').fetchone()[0] == 4
    from personal_agent.trust import Trust
    assert Trust(store).audit('demo')['content_disclosed'] is False
    from personal_agent.memory import Memory
    from personal_agent.journal import Journal
    from datetime import datetime, timedelta, timezone
    trust, memory = Trust(store), Memory(store)
    identifier = memory.remember('wheel', 'synthetic renewal needle', 'fixture://wheel', sensitivity='internal')
    mark = trust.mark('memory', 'wheel', identifier)
    memory.rebuild_index()
    assert memory.search('needle', project_id='wheel') == []
    trust.review_mark(mark, 'internal')
    assert memory.search('needle', project_id='wheel')[0]['id'] == identifier
    store.connection.execute("UPDATE data_admissions SET expires_at='2000-01-01T00:00:00Z' WHERE object_id=?", (identifier,))
    valid = memory.remember('wheel', 'synthetic valid needle', 'fixture://valid', sensitivity='internal')
    assert [r['id'] for r in memory.search('needle', project_id='wheel')] == [valid]
    # More than the former eight-result limit must not starve the older valid hit.
    for i in range(12):
        stale = memory.remember('wheel', 'synthetic stale needle', 'fixture://stale', sensitivity='internal')
        store.connection.execute("UPDATE data_admissions SET digest=? WHERE object_id=?", ('0' * 64, stale))
    assert [r['id'] for r in memory.search('needle', project_id='wheel', limit=1)] == [valid]
    meta = trust.review_metadata('memory', identifier, 'wheel')
    trust.renew('memory', identifier, 'wheel', meta['digest'], 'internal',
                expires_at=(datetime.now(timezone.utc) + timedelta(days=90)).isoformat())
    assert [r['id'] for r in memory.search('needle', project_id='wheel')] == [valid, identifier]
    memory.rebuild_index()
    assert [r['id'] for r in memory.search('needle', project_id='wheel')] == [valid, identifier]
    assert Journal(store).historical_audit(result['task']['task_id'], result['task']['project_id'])['content_withheld']
    from personal_agent.vault import DisabledWindowsCredentialManager
    assert DisabledWindowsCredentialManager.enabled is False
    assert specification('connector-gates.json')['all_adapters_disabled'] is True
    previews = Previews(store)
    preview = previews.create({'synthetic': True}, clock=1000)
    assert preview['permissions_verified']
    assert previews.cleanup(clock=10000)['removed'] == 1
print('PASS: installed wheel resources, offline task, trust lifecycle and private preview outside checkout')
"""
        result = subprocess.run([sys.executable, "-I", "-c", program, str(target),
                                 str(Path(temporary) / "home")], cwd=temporary,
                                capture_output=True, text=True, check=False, timeout=30)
        if result.returncode:
            raise SystemExit(result.stderr or result.stdout)
        print(result.stdout.strip())


if __name__ == "__main__":
    main()
