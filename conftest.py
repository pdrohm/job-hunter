"""Let pytest run the script-style tests (`<bot>/test_*.py`).

Each test file is a plain script: it prints one line per check and exits 1 when
a check fails. pytest runs each one as `python -m <bot>.test_x` from the repo
root, so one pytest item = one test file. Run a single file the same way:
`.venv/bin/python -m job_hunter.test_scraper`.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent


def pytest_collect_file(parent, file_path):
    if file_path.suffix == ".py" and file_path.name.startswith("test_") and file_path.parent != ROOT:
        return ScriptFile.from_parent(parent, path=file_path)


class ScriptFile(pytest.File):
    def collect(self):
        yield ScriptItem.from_parent(self, name="checks")


class ScriptItem(pytest.Item):
    def runtest(self):
        module = ".".join(self.path.relative_to(ROOT).with_suffix("").parts)
        proc = subprocess.run([sys.executable, "-m", module], cwd=ROOT, capture_output=True, text=True)
        self.output = proc.stdout + proc.stderr
        match = re.search(r"Results: (\d+)/(\d+) passed", proc.stdout)
        if match:
            self.user_properties.append(("checks", f"{match[1]}/{match[2]}"))
        if proc.returncode != 0:
            raise ScriptFailed(self.output)

    def repr_failure(self, excinfo):
        if isinstance(excinfo.value, ScriptFailed):
            return str(excinfo.value)
        return super().repr_failure(excinfo)

    def reportinfo(self):
        return self.path, None, f"{self.path.relative_to(ROOT)}"


class ScriptFailed(Exception):
    pass
