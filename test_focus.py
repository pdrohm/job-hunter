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
    filter_india_full_text,
    filter_post_intent,
    filter_region,
    filter_tech_relevance,
    filter_top_markets,
    limit_per_company,
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
print("\n━━━ Excluded Country Tests ━━━")

from focus import located_in, looks_portuguese
from rn_linkedin_scraper import filter_excluded_countries

test("'Brazil' excluded", located_in("Brazil", ["Brazil"]) == "Brazil")
test("City, state, Brazil excluded", bool(located_in("São Paulo, São Paulo, Brazil", ["Brazil"])))
test("Metro area without country excluded", bool(located_in("Greater Porto Alegre", ["Brazil"])))
test("Florianópolis excluded", bool(located_in("Florianópolis, Santa Catarina", ["Brazil"])))
test("Mexico kept", not located_in("Guadalajara, Jalisco, Mexico", ["Brazil"]))
test("Latin America kept", not located_in("Latin America", ["Brazil"]))
test("Remote kept", not located_in("Remote", ["Brazil"]))
test("No countries → nothing excluded", not located_in("Brazil", []))
test("Other country works", bool(located_in("Lisbon, Portugal", ["Portugal"])))
test("Portuguese post detected", looks_portuguese("Vaga remota para desenvolvedor React Native, contratação PJ"))
test("English post not Portuguese", not looks_portuguese("Hiring a remote React Native developer, contract role"))
test("One word is not enough", not looks_portuguese("Remote role, we hire in LATAM (remoto ok)"))

opps = [
    make_opp(title="RN BR", location="Brazil"),
    make_opp(title="RN MX", location="Mexico City, Mexico"),
    make_opp(title="Post PT", result_type=ResultType.POST, location="Not specified",
             url="https://www.linkedin.com/posts/pt", description="Estamos contratando! Vaga remota React Native."),
    make_opp(title="Post EN", result_type=ResultType.POST, location="Not specified",
             url="https://www.linkedin.com/posts/en", description="We are hiring a remote React Native engineer."),
]
kept = [o.title for o in filter_excluded_countries(opps, ["Brazil"])]
test("Country filter drops BR job and PT post", kept == ["RN MX", "Post EN"], str(kept))
test("Empty list keeps all", len(filter_excluded_countries(opps, [])) == 4)

# Same job posted in Brazil and Argentina: the Argentina copy must survive
from unittest import mock as _mock
import rn_linkedin_scraper as rls
br = make_opp(title="React Native Dev", company_or_author="Acme", location="Brazil",
              url="https://www.linkedin.com/jobs/view/1111111111/", job_id="1111111111", source="linkedin_jobs")
ar = make_opp(title="React Native Dev", company_or_author="Acme", location="Buenos Aires, Argentina",
              url="https://www.linkedin.com/jobs/view/2222222222/", job_id="2222222222", source="linkedin_jobs")
with _mock.patch.object(rls, "scrape_linkedin_jobs_page", return_value=[br, ar]), \
        _mock.patch.object(rls, "time"):
    out = rls.run_scraper_with_progress(engines=["linkedin"], enrich=False, exclude_countries=["Brazil"],
                                        exclude_sponsorship=False)
test("Multi-country repost keeps non-excluded copy", [o.location for o in out] == ["Buenos Aires, Argentina"],
     str([o.location for o in out]))


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
from rn_linkedin_scraper import is_onsite_or_hybrid
test("Spanish/Portuguese hybrid and onsite caught",
     is_onsite_or_hybrid("Desarrollador Fullstack - HIBRIDO") and is_onsite_or_hybrid("Vaga presencial em SP")
     and not is_onsite_or_hybrid("100% remoto"))
kept = filter_posts_not_remote(posts)
test("Posts need remote, no hybrid", [o.title for o in kept] == ["Post A"], str([o.title for o in kept]))

posts = [
    make_opp(title="Post A", result_type=ResultType.POST, url="https://www.linkedin.com/posts/a",
             description="Remote RN role. Immediate joiners preferred."),
    make_opp(title="Post B", result_type=ResultType.POST, url="https://www.linkedin.com/posts/b",
             description="Remote RN role, LATAM."),
]
posts.append(make_opp(title="Post C", result_type=ResultType.POST, url="https://www.linkedin.com/posts/c",
                      description="Join NeuSpaarX Technologies Pvt. Ltd. Remote RN role."))
kept = filter_india_full_text(posts)
test("India recruiter phrases dropped", [o.title for o in kept] == ["Post B"], str([o.title for o in kept]))

import rn_linkedin_scraper as _rls
_opps = _rls.linkedin_posts_to_opportunities([{
    "url": "https://www.linkedin.com/posts/abc_hiring-share-7515472611372556289-zVSJ/",
    "text": "We are hiring a React Native dev\nRemote, LATAM. Contractor.", "author": "Jane Doe",
}], "q")
test("LinkedIn post → Opportunity", _opps[0].title == "We are hiring a React Native dev"
     and _opps[0].company_or_author == "Jane Doe" and _opps[0].posted_at.startswith("2026")
     and _opps[0].open_abroad and _opps[0].contractor and _opps[0].source == "linkedin_posts",
     str(_opps[0]))

posts = [
    make_opp(title="#opentowork #reactnative", result_type=ResultType.POST, url="https://www.linkedin.com/posts/s",
             description="Open to Work | Senior React Native Engineer | Remote. I'm currently exploring opportunities."),
    make_opp(title="#hiring #reactnative", result_type=ResultType.POST, url="https://www.linkedin.com/posts/h",
             description="We are hiring: React Native Developer, full remote."),
    make_opp(title="Post", result_type=ResultType.POST, url="https://www.linkedin.com/posts/t",
             description="5 tips for React Native performance."),
    make_opp(title="Intern", result_type=ResultType.POST, url="https://www.linkedin.com/posts/i",
             description="We're looking for React Native Mobile Developer Interns. Remote."),
    make_opp(title="Job", description="React Native role"),
]
from focus import is_job_seeker_post
test("Job seeker phrases (curly apostrophe too)",
     is_job_seeker_post("I’m open to new opportunities! I’m currently exploring Senior roles")
     and is_job_seeker_post("Hi everyone! I'm looking for my next role")
     and is_job_seeker_post("Now, I’m looking for my next big challenge!")
     and not is_job_seeker_post("Misaq is hiring a Senior React Native Developer"))
kept = [o.title for o in filter_post_intent(posts)]
test("Post intent: hiring kept, opentowork and tips dropped, jobs untouched",
     kept == ["#hiring #reactnative", "Job"], str(kept))

jobs = [
    make_opp(title="Job A", location="Worldwide", description="Remote team. Based in India, Bengaluru office."),
    make_opp(title="Job B", location="Worldwide", description="Remote team with offices in US and India."),
]
kept = filter_india_full_text(jobs)
test("Job 'based in India' dropped, India office kept", [o.title for o in kept] == ["Job B"],
     str([o.title for o in kept]))

opps = [
    make_opp(title="Senior React Native Engineer", snippet="", description=""),
    make_opp(title="Mobile Developer", description="We use Expo and TypeScript."),
    make_opp(title="Mobile Engineer (iOS & Android)", description="Stack: React, TypeScript, GraphQL."),
    make_opp(title="iOS Engineer", description="Swift and SwiftUI only."),
    make_opp(title="Multiplayer Game Programmer (Unity / C#)", source="linkedin_jobs",
             source_query='"react native" developer remote', description="Unity, C#, Photon."),
    make_opp(title="Senior Frontend Developer", description="React, Next.js, Tailwind."),
    make_opp(title="Post", result_type=ResultType.POST, url="https://www.linkedin.com/posts/x",
             description="#hiring #reactnative #remote"),
]
for o in opps[1:]:
    o.snippet = ""
kept = [o.title for o in filter_tech_relevance(opps, [], rn_only=True)]
test("RN filter keeps RN/Expo/JS-mobile, drops native, Unity, web",
     kept == ["Senior React Native Engineer", "Mobile Developer", "Mobile Engineer (iOS & Android)", "Post"],
     str(kept))

opps = [
    make_opp(title="A", location="Buenos Aires, Argentina"),
    make_opp(title="B", location="Latin America"),
    make_opp(title="C", location="Worldwide"),
    make_opp(title="D", location="London, England, United Kingdom", description="Hybrid-free, UK team."),
    make_opp(title="E", location="United Kingdom", description="100% remote - Worldwide"),
    make_opp(title="F", location="United States", description="Open to contractors in LATAM."),
    make_opp(title="G", location="Albuquerque, New Mexico, United States"),
    make_opp(title="H", location="Rome, Latium, Italy", description="A global leader in banking."),
    make_opp(title="I", location="Germany", open_abroad=True),
    make_opp(title="J", location="Mexico City Metropolitan Area"),
    make_opp(title="Post", result_type=ResultType.POST, url="https://www.linkedin.com/posts/y", location="Not specified"),
]
kept = [o.title for o in filter_region(opps)]
test("Region filter keeps LATAM/worldwide only", kept == ["A", "B", "C", "E", "F", "I", "J", "Post"], str(kept))

opps = [
    make_opp(title="Senior React Native Engineer", description=""),
    make_opp(title="Mobile Engineer", description="Our app is built with Expo."),
    make_opp(title="Mobile Engineer (iOS & Android)", description="Stack: React, TypeScript, GraphQL."),
    make_opp(title="Frontend Engineer", description="React, Next.js. React Native is a plus."),
    make_opp(title="Software Engineer", description="Ship our React Native app. Expo, EAS, TypeScript."),
]
for o in opps:
    o.snippet = ""
kept = [o.title for o in filter_tech_relevance(opps, [], rn_only=True, strict=True)]
test("Strict RN filter: RN must be the job, not a side note",
     kept == ["Senior React Native Engineer", "Mobile Engineer", "Software Engineer"], str(kept))

opps = [
    make_opp(title="A", location="United States", description="Open to contractors in LATAM."),
    make_opp(title="B", location="Austin, TX", description="Remote, worldwide."),
    make_opp(title="C", location="Latin America", description="US-based startup, 4h overlap with EST."),
    make_opp(title="D", location="Latin America", description="Remote role, paid in USD via Deel."),
    make_opp(title="E", location="Argentina", description="Remote React Native role."),
    make_opp(title="F", location="Mexico City Metropolitan Area",
             description="Buscamos desarrollador React Native con experiencia. Ofrecemos beneficios."),
    make_opp(title="G", location="Worldwide", description="We are a fintech based in London."),
    make_opp(title="H", location="Colombia", description="UTC-5 time zone, remote team."),
    make_opp(title="Post US", result_type=ResultType.POST, url="https://www.linkedin.com/posts/a",
             description="#hiring React Native dev, LATAM welcome, PST overlap"),
    make_opp(title="Post local", result_type=ResultType.POST, url="https://www.linkedin.com/posts/b",
             description="#hiring React Native dev, remote LATAM"),
]
kept = [o.title for o in filter_top_markets(opps)]
test("Top-markets filter keeps US/Canada/Europe companies, drops local LATAM",
     kept == ["A", "B", "C", "D", "G", "Post US"], str(kept))

opps = [
    make_opp(title="A", company_or_author="BairesDev"),
    make_opp(title="B", company_or_author="Acme"),
    make_opp(title="C", company_or_author="bairesdev "),
]
kept = [o.title for o in limit_per_company(opps, limit=1)]
test("One result per company (best first)", kept == ["A", "B"], str(kept))

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
