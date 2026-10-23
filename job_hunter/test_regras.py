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


def job(title="React Native Engineer", company="Acme", snippet="", description="", age=None, posted=""):
    return Opportunity(title=title, result_type="job", company_or_author=company, location="Remote",
                       url="https://x", snippet=snippet, description=description, original_age_days=age,
                       posted_at=posted)


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

print("\nregras: exigir_palavras and idade_max_dias")
must = {"exigir_palavras": ["react native", "expo"]}
test("job with a wanted word is kept", regras.skip_reason(job(description="We use Expo"), must) == "")
test("job with none of the wanted words is skipped", regras.skip_reason(job("Flutter Dev"), must) != "")
young = {"idade_max_dias": 3}
test("job of 2 days is kept", regras.skip_reason(job(age=2), young) == "")
test("job of 5 days is skipped", regras.skip_reason(job(age=5), young) != "")
test("unknown age is kept", regras.skip_reason(job(), young) == "")
test("age from posted_at", regras.skip_reason(job(posted="2020-01-01"), young) != "")
test("bad posted_at is kept", regras.skip_reason(job(posted="ontem"), young) == "")

print("\nregras: file and CLI")
with tempfile.TemporaryDirectory() as d:
    os.environ["WATCH_RULES_FILE"] = str(Path(d) / "regras.json")
    test("missing file = empty rules",
         regras.load() == {**{k: [] for k in regras.KEYS}, **{k: None for k in regras.NUMBERS}})
    regras.main(["adicionar", "ignorar_cargos", "tech lead"])
    regras.main(["adicionar", "ignorar_cargos", "Tech Lead"])  # same term, other case: no duplicate
    test("adicionar saves once", regras.load()["ignorar_cargos"] == ["Tech Lead"])
    regras.main(["remover", "ignorar_cargos", "tech lead"])
    test("remover", regras.load()["ignorar_cargos"] == [])
    test("bad key is refused", regras.main(["adicionar", "outra", "x"]) == 2)
    regras.main(["adicionar", "ignorar_cargos", "tech lead"])
    regras.main(["definir", "idade_max_dias", "3"])
    test("definir saves a number and keeps the lists",
         regras.load()["idade_max_dias"] == 3 and regras.load()["ignorar_cargos"] == ["tech lead"])
    test("definir refuses 0 and text", regras.main(["definir", "idade_max_dias", "0"]) == 2
         and regras.main(["definir", "idade_max_dias", "x"]) == 2)
    regras.main(["definir", "idade_max_dias", "nada"])
    test("definir nada turns it off", regras.load()["idade_max_dias"] is None)
    Path(os.environ["WATCH_RULES_FILE"]).write_text("{broken", encoding="utf-8")
    test("broken file = empty rules", regras.load()["ignorar_cargos"] == [])
    del os.environ["WATCH_RULES_FILE"]

print(f"\n{results['passed']} passed, {results['failed']} failed")
if results["failed"]:
    sys.exit(1)
