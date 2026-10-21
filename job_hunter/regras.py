"""
User rules for which jobs to skip, kept in a small JSON file so they can
change without touching code (the Mike assistant edits them by voice).

File: WATCH_RULES_FILE, default ~/.job-hunter/regras.json
    {"ignorar_cargos": ["tech lead"], "ignorar_empresas": [], "ignorar_palavras": []}

- ignorar_cargos: skip when the title contains the term (whole words, any case)
- ignorar_empresas: skip when the company/author contains the term
- ignorar_palavras: skip when the title, snippet or description contains the term

A missing file means no rules (e.g. on the GitHub runner).

CLI:
    python -m job_hunter.regras listar
    python -m job_hunter.regras adicionar ignorar_cargos "tech lead"
    python -m job_hunter.regras remover ignorar_cargos "tech lead"
"""

import json
import os
import re
import sys
import tempfile
from pathlib import Path

KEYS = ("ignorar_cargos", "ignorar_empresas", "ignorar_palavras")


def rules_path() -> Path:
    return Path(os.getenv("WATCH_RULES_FILE") or Path.home() / ".job-hunter" / "regras.json")


def load(path: Path = None) -> dict[str, list[str]]:
    path = path or rules_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        data = {}
    return {k: [str(t) for t in data.get(k, []) if str(t).strip()] for k in KEYS}


def save(rules: dict[str, list[str]], path: Path = None):
    """Atomic write: a crash mid-write never leaves a broken file."""
    path = path or rules_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({k: rules.get(k, []) for k in KEYS}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        os.unlink(tmp)
        raise


def _matcher(terms: list[str]):
    if not terms:
        return None
    # Whole words: "lead" must not match "leading", but "tech lead" matches "Tech Lead (RN)".
    alts = "|".join(re.escape(t.strip()).replace(r"\ ", r"[\s-]+") for t in terms)
    return re.compile(rf"(?<!\w)(?:{alts})(?!\w)", re.IGNORECASE)


def skip_reason(opp, rules: dict[str, list[str]]) -> str:
    """Return why this job breaks a rule, or "" when it is fine."""
    checks = (
        ("ignorar_cargos", opp.title or ""),
        ("ignorar_empresas", opp.company_or_author or ""),
        ("ignorar_palavras", " ".join([opp.title or "", opp.snippet or "", opp.description or ""])),
    )
    for key, text in checks:
        m = _matcher(rules.get(key, []))
        if m and (hit := m.search(text)):
            return f"{key}: {hit.group(0)}"
    return ""


def apply(results: list, rules: dict[str, list[str]] = None) -> list:
    rules = load() if rules is None else rules
    return [o for o in results if not skip_reason(o, rules)]


def main(argv: list[str]) -> int:
    rules = load()
    if not argv or argv[0] == "listar":
        print(json.dumps(rules, ensure_ascii=False, indent=2))
        return 0
    if len(argv) != 3 or argv[0] not in ("adicionar", "remover") or argv[1] not in KEYS:
        print(f"uso: python -m job_hunter.regras listar | adicionar|remover <{'|'.join(KEYS)}> <termo>")
        return 2
    action, key, term = argv[0], argv[1], argv[2].strip()
    current = [t for t in rules[key] if t.lower() != term.lower()]
    if action == "adicionar":
        current.append(term)
    rules[key] = current
    save(rules)
    print(f"{action}: {key} = {term!r}. Agora: {rules[key]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
