#!/usr/bin/env python3
"""
Tests for the user rules file (job_hunter/regras.py): matching, the CLI
and the empty/missing file.
"""

import os
import sys
import tempfile
from pathlib import Path

from job_hunter import regras
from job_hunter.rn_linkedin_scraper import Opportunity

PASS = "✓"
FAIL = "✗"
results = {"passed": 0, "failed": 0}


def test(name: str, condition: bool, detail: str = ""):
    if condition:
        results["passed"] += 1
        print(f"  {PASS} {name}")
    else:
        results["failed"] += 1
        print(f"  {FAIL} {name}" + (f" — {detail}" if detail else ""))


def job(title="React Native Engineer", company="Acme", snippet="", description=""):
    return Opportunity(title=title, result_type="job", company_or_author=company,
                       location="Remote", url="https://x", snippet=snippet, description=description)


print("\nregras: matching")
rules = {"ignorar_cargos": ["tech lead"], "ignorar_empresas": ["BadCo"], "ignorar_palavras": ["blockchain"]}
test("tech lead in title is skipped", regras.skip_reason(job("Tech Lead - React Native"), rules) != "")
test("hyphenated tech-lead is skipped", regras.skip_reason(job("Tech-Lead Mobile"), rules) != "")
test("plain engineer is kept", regras.skip_reason(job("Senior React Native Engineer"), rules) == "")
test("whole words only (lead != leading)",
     regras.skip_reason(job("Engineer, leading tech"), {"ignorar_cargos": ["lead"]}) == "")
test("company rule", regras.skip_reason(job(company="BadCo Inc."), rules) != "")
test("word in description", regras.skip_reason(job(description="We build on blockchain"), rules) != "")
test("apply filters the list",
     [o.title for o in regras.apply([job("Tech Lead"), job("RN Dev")], rules)] == ["RN Dev"])
test("no rules keeps everything", len(regras.apply([job("Tech Lead")], {})) == 1)

print("\nregras: file and CLI")
with tempfile.TemporaryDirectory() as d:
    os.environ["WATCH_RULES_FILE"] = str(Path(d) / "regras.json")
    test("missing file = empty rules", regras.load() == {k: [] for k in regras.KEYS})
    regras.main(["adicionar", "ignorar_cargos", "tech lead"])
    regras.main(["adicionar", "ignorar_cargos", "Tech Lead"])  # same term, other case: no duplicate
    test("adicionar saves once", regras.load()["ignorar_cargos"] == ["Tech Lead"])
    regras.main(["remover", "ignorar_cargos", "tech lead"])
    test("remover", regras.load()["ignorar_cargos"] == [])
    test("bad key is refused", regras.main(["adicionar", "outra", "x"]) == 2)
    Path(os.environ["WATCH_RULES_FILE"]).write_text("{broken", encoding="utf-8")
    test("broken file = empty rules", regras.load()["ignorar_cargos"] == [])
    del os.environ["WATCH_RULES_FILE"]

print(f"\n{results['passed']} passed, {results['failed']} failed")
if results["failed"]:
    sys.exit(1)
