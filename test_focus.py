#!/usr/bin/env python3
"""
Tests for focus rules: sponsorship blockers, contractor detection,
country-only penalty, and the related pipeline filters.
"""

import sys

from focus import is_contractor, looks_country_only, sponsorship_blocker
from rn_linkedin_scraper import (
    Opportunity,
    ResultType,
    filter_contract,
    filter_india_posts,
    filter_posts_not_remote,
    filter_sponsorship,
    rank_opportunities,
)

PASS = "✓"
FAIL = "✗"
results = {"passed": 0, "failed": 0}


def test(name: str, condition: bool, detail: str = ""):
    status = PASS if condition else FAIL
    results["passed" if condition else "failed"] += 1
    print(f"  {status} {name}" + (f"  ({detail})" if detail and not condition else ""))


def make_opp(**kwargs) -> Opportunity:
    defaults = {
        "title": "React Native Developer",
        "result_type": ResultType.JOB,
        "company_or_author": "TechCo",
        "location": "Remote",
        "url": f"https://www.linkedin.com/jobs/view/{abs(hash(str(kwargs))) % 10**10:010d}/",
        "snippet": "React Native role",
    }
    defaults.update(kwargs)
    return Opportunity(**defaults)


# ─────────────────────────────────────────────
print("\n━━━ Sponsorship Blocker Tests ━━━")

blocked = [
    "We are unable to sponsor visas at this time.",
    "We do not provide visa sponsorship.",
    "This role does not offer sponsorship.",
    "Sponsorship is not available for this position.",
    "Must be authorized to work in the United States.",
    "Candidates must be legally authorized to work in the US without sponsorship.",
    "You must have the right to work in the UK.",
    "Must be eligible to work in Canada.",
    "US Citizens only.",
    "Must be a U.S. citizen or green card holder.",
    "Active Secret clearance required.",
    "Must reside in the United States.",
    "US-based only.",
    "W2 only, no C2C.",
    "Will you now or in the future require sponsorship? We cannot sponsor.",
    "Visa Sponsorship: We are unable to offer visa sponsorship for this position.",
    "You must be authorized to work for any employer in the U.S.",
    "We are unable to sponsor or take over sponsorship of an employment visa.",
    "We are open to qualified applicants from anywhere in the U.S.",
]
for text in blocked:
    test(f"Blocks: {text[:50]}", bool(sponsorship_blocker(text)))

allowed = [
    "Fully remote, work from anywhere. Paid via Deel.",
    "We hire contractors across LATAM.",
    "Remote role open to candidates worldwide.",
    "Visa sponsorship available for relocation.",
    "Equal opportunity regardless of race, national origin, citizenship, disability.",
    "If you reside outside the United States, by applying you confirm consent.",
    "Join our team as a senior React Native engineer.",
    "",
]
for text in allowed:
    test(f"Allows: {text[:50] or '(empty)'}", not sponsorship_blocker(text), sponsorship_blocker(text))


# ─────────────────────────────────────────────
print("\n━━━ Contractor Detection Tests ━━━")

test("LinkedIn 'Contract' type", is_contractor("", "Contract"))
test("LinkedIn 'Temporary' type", is_contractor("", "Temporary"))
test("Text: independent contractor", is_contractor("Hiring an independent contractor"))
test("Text: B2B", is_contractor("B2B agreement, remote"))
test("Text: PJ", is_contractor("Vaga PJ remota"))
test("Text: hourly rate", is_contractor("Hourly rate $40-60/hr"))
test("Full-time without contractor words", not is_contractor("Great benefits", "Full-time"))
test("Full-time but says contractor", is_contractor("Hired as a contractor via Deel", "Full-time"))
test("Plain employee text", not is_contractor("Full-time employee with 401k"))


# ─────────────────────────────────────────────
print("\n━━━ Country-only Location Tests ━━━")

test("US only remote", looks_country_only("United States", "Remote role"))
test("City, state US", looks_country_only("New York, NY", ""))
test("UK only", looks_country_only("United Kingdom", ""))
test("US but says LATAM", not looks_country_only("United States", "We hire in LATAM"))
test("US but worldwide", not looks_country_only("United States", "open worldwide"))
test("'Anywhere in the U.S.' is still US only", looks_country_only("United States", "applicants from anywhere in the U.S."))
test("Brazil not penalised", not looks_country_only("Brazil", ""))
test("São Paulo not penalised", not looks_country_only("São Paulo, São Paulo, Brazil", ""))
test("Remote not penalised", not looks_country_only("Remote", ""))
test("Empty location", not looks_country_only("", ""))


# ─────────────────────────────────────────────
print("\n━━━ Pipeline Filter Tests ━━━")

opps = [
    make_opp(title="RN Dev A", description="Must be authorized to work in the US."),
    make_opp(title="RN Dev B", description="Contractors welcome from anywhere."),
]
kept = filter_sponsorship(opps)
test("filter_sponsorship drops blocker", [o.title for o in kept] == ["RN Dev B"], str([o.title for o in kept]))

opps = [
    make_opp(title="RN A", employment_type="Contract"),
    make_opp(title="RN B", employment_type="Full-time", description="Great benefits"),
    make_opp(title="RN C", description="B2B contract"),
]
kept = filter_contract(opps)
test("filter_contract keeps contract only", [o.title for o in kept] == ["RN A", "RN C"], str([o.title for o in kept]))

posts = [
    make_opp(title="Post A", result_type=ResultType.POST, url="https://www.linkedin.com/posts/a",
             description="Hiring RN dev, 100% remote."),
    make_opp(title="Post B", result_type=ResultType.POST, url="https://www.linkedin.com/posts/b",
             description="Hiring RN dev, hybrid in Berlin."),
    make_opp(title="Post C", result_type=ResultType.POST, url="https://www.linkedin.com/posts/c",
             description="Hiring RN dev, office only."),
]
kept = filter_posts_not_remote(posts)
test("Posts need remote, no hybrid", [o.title for o in kept] == ["Post A"], str([o.title for o in kept]))

posts = [
    make_opp(title="Post A", result_type=ResultType.POST, url="https://www.linkedin.com/posts/a",
             description="Remote RN role. Immediate joiners preferred."),
    make_opp(title="Post B", result_type=ResultType.POST, url="https://www.linkedin.com/posts/b",
             description="Remote RN role, LATAM."),
]
kept = filter_india_posts(posts)
test("India recruiter phrases dropped", [o.title for o in kept] == ["Post B"], str([o.title for o in kept]))

ranked = rank_opportunities([
    make_opp(title="React Native Developer", location="United States", snippet="React Native role"),
    make_opp(title="React Native Developer", location="Brazil", snippet="React Native role, LATAM contractor"),
])
test("Open-to-abroad job ranks above US-only", ranked[0].location == "Brazil",
     f"{ranked[0].location}={ranked[0].relevance_score} vs {ranked[1].relevance_score}")


# ─────────────────────────────────────────────
print(f"\n{'━' * 50}")
total = results["passed"] + results["failed"]
print(f"Results: {results['passed']}/{total} passed", end="")
if results["failed"]:
    print(f"  ({results['failed']} FAILED)")
    sys.exit(1)
print("  ✓ All tests passed!")
