"""Load the built wheel outside its checkout and run the offline fixture workflow."""
import subprocess
import sys
import tempfile
import zipfile
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
        with zipfile.ZipFile(wheels[0]) as archive:
            archive.extractall(target)
        program = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import personal_agent
from personal_agent.config import Paths, specification
from personal_agent.demo import run_demo
assert Path(personal_agent.__file__).is_relative_to(Path(sys.argv[1]))
assert specification('model-config.json')['primary_local']['model'] == 'qwen3.5:9b'
result = run_demo(Paths(Path(sys.argv[2])))
assert result['task']['state'] == 'completed', result['task']['block_reason']
assert result['result']['verified_steps'] == 2
print('PASS: wheel resources and offline task outside checkout')
"""
        result = subprocess.run([sys.executable, "-c", program, str(target),
                                 str(Path(temporary) / "home")], cwd=temporary,
                                capture_output=True, text=True, check=False, timeout=30)
        if result.returncode:
            raise SystemExit(result.stderr or result.stdout)
        print(result.stdout.strip())


if __name__ == "__main__":
    main()
