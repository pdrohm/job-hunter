#!/usr/bin/env python3
"""
Tests for the React Native LinkedIn Scraper
Validates India filtering, relevance scoring, and deduplication logic.
"""

import json
import sys

# Import from main module
from rn_linkedin_scraper import (
    Opportunity,
    ResultType,
    compute_relevance,
    deduplicate,
    filter_india,
    has_preferred_region,
    is_india_related,
    rank_opportunities,
)

PASS = "✓"
FAIL = "✗"
results = {"passed": 0, "failed": 0, "tests": []}


def test(name: str, condition: bool, detail: str = ""):
    status = PASS if condition else FAIL
    results["passed" if condition else "failed"] += 1
    results["tests"].append({"name": name, "passed": condition})
    print(f"  {status} {name}" + (f"  ({detail})" if detail and not condition else ""))


def make_opp(**kwargs) -> Opportunity:
    defaults = {
        "title": "React Native Developer",
        "result_type": ResultType.JOB,
        "company_or_author": "TechCo",
        "location": "Remote",
        "url": f"https://linkedin.com/jobs/{hash(str(kwargs))}",
        "snippet": "Looking for a React Native developer",
    }
    defaults.update(kwargs)
    return Opportunity(**defaults)


# ─────────────────────────────────────────────
# India Filter Tests
# ─────────────────────────────────────────────
print("\n━━━ India Filter Tests ━━━")

# Direct country mentions
test("Detects 'India' directly", is_india_related("Remote - India"))
test("Detects 'india' lowercase", is_india_related("Based in india"))
test("Detects 'INDIA' uppercase", is_india_related("Location: INDIA"))

# Major cities
test("Detects Bangalore", is_india_related("Office in Bangalore"))
test("Detects Bengaluru", is_india_related("Bengaluru, Karnataka"))
test("Detects Mumbai", is_india_related("Mumbai headquarters"))
test("Detects Delhi", is_india_related("New Delhi office"))
test("Detects Hyderabad", is_india_related("Hyderabad tech park"))
test("Detects Pune", is_india_related("Our Pune team"))
test("Detects Chennai", is_india_related("Chennai campus"))
test("Detects Gurgaon", is_india_related("Gurgaon, Haryana"))
test("Detects Gurugram", is_india_related("Located in Gurugram"))
test("Detects Noida", is_india_related("Noida sector 62"))

# Secondary cities
test("Detects Kolkata", is_india_related("Kolkata branch"))
test("Detects Ahmedabad", is_india_related("Ahmedabad Gujarat"))
test("Detects Kochi", is_india_related("Office in Kochi"))
test("Detects Coimbatore", is_india_related("Coimbatore location"))
test("Detects Vizag", is_india_related("Vizag development center"))

# States
test("Detects Karnataka", is_india_related("Karnataka, India"))
test("Detects Maharashtra", is_india_related("Maharashtra region"))
test("Detects Telangana", is_india_related("Telangana state"))

# Remote + India combos
test("Detects 'Remote - India'", is_india_related("Remote - India"))
test("Detects 'Remote (India)'", is_india_related("Remote (India)"))
test("Detects 'India - Remote'", is_india_related("India - Remote"))
test("Detects 'WFH India'", is_india_related("WFH India"))
test("Detects 'Hiring in India'", is_india_related("We are hiring in India"))
test("Detects 'Based in India'", is_india_related("Team based in India"))

# Should NOT match
test("Ignores 'Indiana'", not is_india_related("Indianapolis, Indiana"))
test("Ignores US locations", not is_india_related("San Francisco, CA"))
test("Ignores 'Remote US'", not is_india_related("Remote - US"))
test("Ignores Europe", not is_india_related("Berlin, Germany"))
test("Ignores Brazil", not is_india_related("São Paulo, Brazil"))
test("Ignores Canada", not is_india_related("Toronto, Canada"))
test("Ignores empty string", not is_india_related(""))
test("Ignores generic remote", not is_india_related("Remote worldwide"))

# Edge case: "Indiana" should NOT trigger (word boundary check)
# Note: "Indiana" contains "India" but our regex uses word boundaries
indiana_result = is_india_related("React Native dev in Indiana, US")
test("Indiana (US state) – word boundary", not indiana_result,
     "indiana triggered India filter" if indiana_result else "")


# ─────────────────────────────────────────────
# Preferred Region Tests
# ─────────────────────────────────────────────
print("\n━━━ Preferred Region Tests ━━━")

test("Detects US", has_preferred_region("United States"))
test("Detects Remote", has_preferred_region("Remote"))
test("Detects Germany", has_preferred_region("Berlin, Germany"))
test("Detects Brazil", has_preferred_region("São Paulo, Brazil"))
test("Detects Canada", has_preferred_region("Toronto, Canada"))
test("Detects Worldwide", has_preferred_region("Remote Worldwide"))
test("Detects LATAM", has_preferred_region("Remote LATAM"))
test("No match for random", not has_preferred_region("Mars colony"))


# ─────────────────────────────────────────────
# Relevance Scoring Tests
# ─────────────────────────────────────────────
print("\n━━━ Relevance Scoring Tests ━━━")

score_hiring = compute_relevance(
    "Senior React Native Developer - We are hiring!",
    "Join our team as a senior React Native mobile engineer. Apply now!",
    ResultType.JOB,
)
score_generic = compute_relevance(
    "LinkedIn Post",
    "Some thoughts on mobile development",
    ResultType.POST,
)
test("Hiring post scores higher than generic", score_hiring > score_generic,
     f"{score_hiring} vs {score_generic}")

score_job = compute_relevance("React Native Dev", "Open position", ResultType.JOB)
score_post = compute_relevance("React Native Dev", "Open position", ResultType.POST)
test("Jobs get type bonus", score_job > score_post, f"{score_job} vs {score_post}")

score_high = compute_relevance(
    "React Native Developer - Now Hiring",
    "We are hiring a senior react native mobile engineer. Apply now. Remote position.",
    ResultType.JOB,
)
test("High-intent scores > 40", score_high > 40, f"score={score_high}")

score_low = compute_relevance("Random article", "Technology trends 2024", ResultType.POST)
test("Low-intent scores < 10", score_low < 10, f"score={score_low}")


# ─────────────────────────────────────────────
# Deduplication Tests
# ─────────────────────────────────────────────
print("\n━━━ Deduplication Tests ━━━")

opps = [
    make_opp(url="https://linkedin.com/jobs/view/123"),
    make_opp(url="https://linkedin.com/jobs/view/123"),
    make_opp(url="https://linkedin.com/jobs/view/456"),
    make_opp(url="https://linkedin.com/jobs/view/456/"),  # trailing slash
]
deduped = deduplicate(opps)
test("Removes exact URL dupes", len(deduped) < len(opps))
test("Handles trailing slash normalization", len(deduped) == 2, f"got {len(deduped)}")


# ─────────────────────────────────────────────
# Full Pipeline Filter Test
# ─────────────────────────────────────────────
print("\n━━━ Full Pipeline Filter Tests ━━━")

pipeline_opps = [
    make_opp(title="RN Dev", location="San Francisco, CA", url="https://li.com/1"),
    make_opp(title="RN Dev", location="Bangalore, India", url="https://li.com/2"),
    make_opp(title="RN Dev", location="Remote - Worldwide", url="https://li.com/3"),
    make_opp(title="RN Dev", location="Hyderabad", url="https://li.com/4"),
    make_opp(title="RN Dev", location="Berlin, Germany", url="https://li.com/5"),
    make_opp(title="RN Dev", location="Remote", snippet="Hiring in India", url="https://li.com/6"),
    make_opp(title="RN Dev", location="London, UK", url="https://li.com/7"),
    make_opp(title="RN Dev at Pune office", location="", url="https://li.com/8"),
    make_opp(title="RN Dev", location="São Paulo, Brazil", url="https://li.com/9"),
]

filtered = filter_india(pipeline_opps)
remaining_urls = {o.url for o in filtered}

test("SF kept", "https://li.com/1" in remaining_urls)
test("Bangalore removed", "https://li.com/2" not in remaining_urls)
test("Remote worldwide kept", "https://li.com/3" in remaining_urls)
test("Hyderabad removed", "https://li.com/4" not in remaining_urls)
test("Berlin kept", "https://li.com/5" in remaining_urls)
test("Remote+India snippet removed", "https://li.com/6" not in remaining_urls)
test("London kept", "https://li.com/7" in remaining_urls)
test("Pune in title removed", "https://li.com/8" not in remaining_urls)
test("São Paulo kept", "https://li.com/9" in remaining_urls)
test("5 results remain", len(filtered) == 5, f"got {len(filtered)}")


# ─────────────────────────────────────────────
# Ranking Tests
# ─────────────────────────────────────────────
print("\n━━━ Ranking Tests ━━━")

rank_opps = [
    make_opp(title="Article about tech", snippet="Mobile trends", url="https://li.com/r1"),
    make_opp(
        title="Senior React Native Engineer - Hiring Now",
        snippet="We are hiring. Apply now. React Native. Remote position. Join our team.",
        url="https://li.com/r2",
    ),
    make_opp(
        title="React Native opportunity",
        snippet="Looking for a dev",
        result_type=ResultType.POST,
        url="https://li.com/r3",
    ),
]

ranked = rank_opportunities(rank_opps)
test("Top result is hiring-heavy", ranked[0].url == "https://li.com/r2",
     f"got {ranked[0].url}")
test("Last result is generic article", ranked[-1].url == "https://li.com/r1",
     f"got {ranked[-1].url}")
test("All have scores assigned", all(o.relevance_score >= 0 for o in ranked))


# ─────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────
print(f"\n{'━' * 50}")
total = results["passed"] + results["failed"]
print(f"Results: {results['passed']}/{total} passed", end="")
if results["failed"]:
    print(f"  ({results['failed']} FAILED)")
    sys.exit(1)
else:
    print("  ✓ All tests passed!")
    sys.exit(0)
