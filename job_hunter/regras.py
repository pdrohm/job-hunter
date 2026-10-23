"""
User rules for which jobs to skip, kept in a small JSON file so they can
change without touching code (the Mike assistant edits them by voice).

File: WATCH_RULES_FILE, default ~/.job-hunter/regras.json
    {"ignorar_cargos": ["tech lead"], "ignorar_empresas": [], "ignorar_palavras": [],
     "exigir_palavras": [], "idade_max_dias": 3}

- ignorar_cargos: skip when the title contains the term (whole words, any case)
- ignorar_empresas: skip when the company/author contains the term
- ignorar_palavras: skip when the title, snippet or description contains the term
- exigir_palavras: skip when the title, snippet and description contain none of the terms
- idade_max_dias: skip jobs first posted more than N days ago; watcher.scrape() also searches only that far back

The Mike app edits the same file (filters screen of the "vagas" bot, mike-api filtros.py).

A missing file means no rules (e.g. on the GitHub runner).

CLI:
    python -m job_hunter.regras listar
    python -m job_hunter.regras adicionar ignorar_cargos "tech lead"
    python -m job_hunter.regras remover ignorar_cargos "tech lead"
    python -m job_hunter.regras definir idade_max_dias 3     (or "nada" to turn it off)
"""

import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

KEYS = ("ignorar_cargos", "ignorar_empresas", "ignorar_palavras", "exigir_palavras")  # lists of terms
NUMBERS = ("idade_max_dias",)  # None = off


def rules_path() -> Path:
    return Path(os.getenv("WATCH_RULES_FILE") or Path.home() / ".job-hunter" / "regras.json")


def load(path: Path = None) -> dict[str, list[str]]:
    path = path or rules_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    rules = {k: [str(t) for t in data.get(k) or [] if str(t).strip()] for k in KEYS}
    for k in NUMBERS:
        v = data.get(k)
        rules[k] = float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else None
    return rules


def save(rules: dict[str, list[str]], path: Path = None):
    """Atomic write: a crash mid-write never leaves a broken file."""
    path = path or rules_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            out = {k: rules.get(k, []) for k in KEYS}
            out.update({k: rules[k] for k in NUMBERS if rules.get(k) is not None})
            json.dump(out, f, ensure_ascii=False, indent=2)
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


def age_days(opp) -> Optional[float]:
    """Real age (from the job ID) when known, else from posted_at; None when unknown."""
    if opp.original_age_days is not None:
        return opp.original_age_days
    try:
        posted = datetime.fromisoformat((opp.posted_at or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - posted).total_seconds() / 86400


def skip_reason(opp, rules: dict) -> str:
    """Return why this job breaks a rule, or "" when it is fine."""
    everything = " ".join([opp.title or "", opp.snippet or "", opp.description or ""])
    wanted = _matcher(rules.get("exigir_palavras") or [])
    if wanted and not wanted.search(everything):
        return "exigir_palavras: nenhuma"
    limit, age = rules.get("idade_max_dias"), age_days(opp)
    if limit and age is not None and age > limit:
        return f"idade_max_dias: {age:.0f} dias"
    checks = (
        ("ignorar_cargos", opp.title or ""),
        ("ignorar_empresas", opp.company_or_author or ""),
        ("ignorar_palavras", everything),
    )
    for key, text in checks:
        m = _matcher(rules.get(key) or [])
        if m and (hit := m.search(text)):
            return f"{key}: {hit.group(0)}"
    return ""


def apply(results: list, rules: dict = None) -> list:
    rules = load() if rules is None else rules
    return [o for o in results if not skip_reason(o, rules)]


def main(argv: list[str]) -> int:
    rules = load()
    if not argv or argv[0] == "listar":
        print(json.dumps(rules, ensure_ascii=False, indent=2))
        return 0
    if len(argv) == 3 and argv[0] == "definir" and argv[1] in NUMBERS:
        try:
            value = None if argv[2] == "nada" else float(argv[2])
        except ValueError:
            value = -1
        if value is not None and value <= 0:
            print(f"valor invalido: {argv[2]!r} (um numero maior que 0, ou nada)")
            return 2
        rules[argv[1]] = value
        save(rules)
        print(f"definir: {argv[1]} = {value if value is not None else 'nada'}")
        return 0
    if len(argv) != 3 or argv[0] not in ("adicionar", "remover") or argv[1] not in KEYS:
        print(f"uso: python -m job_hunter.regras listar | adicionar|remover <{'|'.join(KEYS)}> <termo>"
              f" | definir <{'|'.join(NUMBERS)}> <numero|nada>")
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
