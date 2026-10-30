"""Package canonical spec resources without maintaining divergent checked-in copies."""
from pathlib import Path
from shutil import copytree

from setuptools import setup
from setuptools.command.build_py import build_py


class BuildWithContracts(build_py):
    def run(self):
        super().run()
        copytree("spec", Path(self.build_lib) / "personal_agent" / "_spec", dirs_exist_ok=True)


setup(cmdclass={"build_py": BuildWithContracts})
