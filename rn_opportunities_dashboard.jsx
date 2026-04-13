import { useState, useEffect, useMemo } from "react";

// Sample data structure to demonstrate the UI — in production, 
// load from the scraper's JSON output via fetch("/results.json")
const SAMPLE_DATA = {
  metadata: {
    generated_at: new Date().toISOString(),
    total_results: 12,
    tool: "React Native LinkedIn Scraper",
  },
  results: [
    { title: "Senior React Native Engineer", result_type: "job", company_or_author: "Shopify", location: "Remote - North America", url: "https://linkedin.com/jobs/view/1001", snippet: "We are hiring a Senior React Native Engineer. Join our mobile team building cross-platform commerce experiences. Remote position, US/Canada.", relevance_score: 88, scraped_at: new Date().toISOString() },
    { title: "React Native Developer — Join Our Team!", result_type: "post", company_or_author: "Sarah Chen", location: "San Francisco, CA", url: "https://linkedin.com/posts/sarah-chen-1002", snippet: "We're hiring! Looking for a talented React Native developer to join our growing startup. Full-time, competitive salary, equity. Apply now!", relevance_score: 82, scraped_at: new Date().toISOString() },
    { title: "Mobile Engineer (React Native)", result_type: "job", company_or_author: "Klarna", location: "Stockholm, Sweden", url: "https://linkedin.com/jobs/view/1003", snippet: "Open position for a Mobile Engineer with React Native expertise. Work on our next-gen payments app. Hybrid in Stockholm.", relevance_score: 76, scraped_at: new Date().toISOString() },
    { title: "React Native Tech Lead", result_type: "job", company_or_author: "Nubank", location: "São Paulo, Brazil", url: "https://linkedin.com/jobs/view/1004", snippet: "Nubank is looking for a React Native Tech Lead to drive our mobile platform. Remote-first within Brazil. Senior role.", relevance_score: 73, scraped_at: new Date().toISOString() },
    { title: "Hiring React Native Devs — Remote Worldwide", result_type: "post", company_or_author: "Mike Torres", location: "Remote — Worldwide", url: "https://linkedin.com/posts/mike-torres-1005", snippet: "My company is hiring 3 React Native developers for a greenfield project. Remote worldwide, async-first. DM me if interested!", relevance_score: 70, scraped_at: new Date().toISOString() },
    { title: "Full Stack Mobile Developer (React Native + Node)", result_type: "job", company_or_author: "Wealthsimple", location: "Toronto, Canada", url: "https://linkedin.com/jobs/view/1006", snippet: "Join Wealthsimple as a Full Stack Mobile Developer. React Native front-end, Node.js APIs. Hybrid role in Toronto.", relevance_score: 65, scraped_at: new Date().toISOString() },
    { title: "React Native Contractor — 6 Month Engagement", result_type: "job", company_or_author: "Toptal Client", location: "Remote - US/EU", url: "https://linkedin.com/jobs/view/1007", snippet: "Contract React Native developer needed for a 6-month engagement. Cross-platform app rebuild. Competitive hourly rate.", relevance_score: 61, scraped_at: new Date().toISOString() },
    { title: "We're building something new — need RN devs", result_type: "post", company_or_author: "Ana Oliveira", location: "Berlin, Germany", url: "https://linkedin.com/posts/ana-oliveira-1008", snippet: "Exciting opportunity! Our fintech startup in Berlin is hiring React Native engineers. Series A funded, great culture.", relevance_score: 58, scraped_at: new Date().toISOString() },
    { title: "Junior React Native Developer", result_type: "job", company_or_author: "ThoughtWorks", location: "London, UK", url: "https://linkedin.com/jobs/view/1009", snippet: "Entry-level React Native position at ThoughtWorks London. Mentorship program, pair programming, agile team.", relevance_score: 52, scraped_at: new Date().toISOString() },
    { title: "React Native Mobile Developer", result_type: "job", company_or_author: "Delivery Hero", location: "Barcelona, Spain", url: "https://linkedin.com/jobs/view/1010", snippet: "Mobile developer role working on our React Native delivery app. Based in Barcelona, relocation support available.", relevance_score: 48, scraped_at: new Date().toISOString() },
    { title: "Freelance React Native Expert Needed", result_type: "post", company_or_author: "James Park", location: "Remote", url: "https://linkedin.com/posts/james-park-1011", snippet: "Looking for a freelance React Native expert for a 3-month project. Healthcare app, React Native + TypeScript. Reach out if interested.", relevance_score: 44, scraped_at: new Date().toISOString() },
    { title: "React Native + Expo Developer", result_type: "job", company_or_author: "Expo Team", location: "Remote — Global", url: "https://linkedin.com/jobs/view/1012", snippet: "Work on Expo itself! React Native and Expo developer position. Fully remote, global team, open source focused.", relevance_score: 40, scraped_at: new Date().toISOString() },
  ],
};

const ScoreBadge = ({ score }) => {
  const color =
    score >= 70 ? "#10b981" : score >= 40 ? "#f59e0b" : "#6b7280";
  return (
    <div
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: 38,
        height: 38,
        borderRadius: "50%",
        border: `2px solid ${color}`,
        color,
        fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
        fontSize: 12,
        fontWeight: 700,
        flexShrink: 0,
      }}
    >
      {Math.round(score)}
    </div>
  );
};

const TypeTag = ({ type }) => {
  const isJob = type === "job";
  return (
    <span
      style={{
        display: "inline-block",
        padding: "2px 8px",
        borderRadius: 4,
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: "0.08em",
        textTransform: "uppercase",
        background: isJob ? "rgba(16, 185, 129, 0.12)" : "rgba(139, 92, 246, 0.12)",
        color: isJob ? "#34d399" : "#a78bfa",
        border: `1px solid ${isJob ? "rgba(16, 185, 129, 0.25)" : "rgba(139, 92, 246, 0.25)"}`,
      }}
    >
      {type}
    </span>
  );
};

const OpportunityCard = ({ item, index }) => {
  const [hovered, setHovered] = useState(false);
  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: "flex",
        gap: 16,
        padding: "16px 20px",
        borderBottom: "1px solid rgba(255,255,255,0.04)",
        background: hovered ? "rgba(255,255,255,0.02)" : "transparent",
        transition: "background 0.15s ease",
        cursor: "pointer",
        alignItems: "flex-start",
      }}
      onClick={() => window.open(item.url, "_blank", "noopener")}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexShrink: 0 }}>
        <span style={{ color: "#555", fontFamily: "monospace", fontSize: 11, width: 20, textAlign: "right" }}>
          {index + 1}
        </span>
        <ScoreBadge score={item.relevance_score} />
      </div>

      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
          <TypeTag type={item.result_type} />
          <span
            style={{
              fontSize: 14,
              fontWeight: 600,
              color: "#e4e4e7",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {item.title}
          </span>
        </div>

        <div style={{ display: "flex", gap: 16, fontSize: 12, color: "#71717a", marginBottom: 6 }}>
          <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="2" y="7" width="20" height="14" rx="2" ry="2" />
              <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" />
            </svg>
            {item.company_or_author}
          </span>
          <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" />
              <circle cx="12" cy="10" r="3" />
            </svg>
            {item.location}
          </span>
        </div>

        <p
          style={{
            fontSize: 12,
            color: "#a1a1aa",
            lineHeight: 1.5,
            margin: 0,
            overflow: "hidden",
            textOverflow: "ellipsis",
            display: "-webkit-box",
            WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical",
          }}
        >
          {item.snippet}
        </p>
      </div>

      <svg
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="#555"
        strokeWidth="2"
        style={{ flexShrink: 0, marginTop: 4, opacity: hovered ? 1 : 0.3, transition: "opacity 0.15s" }}
      >
        <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
        <polyline points="15 3 21 3 21 9" />
        <line x1="10" y1="14" x2="21" y2="3" />
      </svg>
    </div>
  );
};

export default function App() {
  const [data] = useState(SAMPLE_DATA);
  const [filterType, setFilterType] = useState("all");
  const [searchText, setSearchText] = useState("");
  const [sortBy, setSortBy] = useState("relevance");

  const filtered = useMemo(() => {
    let items = [...data.results];

    if (filterType !== "all") {
      items = items.filter((i) => i.result_type === filterType);
    }

    if (searchText.trim()) {
      const q = searchText.toLowerCase();
      items = items.filter(
        (i) =>
          i.title.toLowerCase().includes(q) ||
          i.company_or_author.toLowerCase().includes(q) ||
          i.location.toLowerCase().includes(q) ||
          i.snippet.toLowerCase().includes(q)
      );
    }

    if (sortBy === "relevance") {
      items.sort((a, b) => b.relevance_score - a.relevance_score);
    } else if (sortBy === "newest") {
      items.sort((a, b) => new Date(b.scraped_at) - new Date(a.scraped_at));
    }

    return items;
  }, [data, filterType, searchText, sortBy]);

  const jobCount = data.results.filter((r) => r.result_type === "job").length;
  const postCount = data.results.filter((r) => r.result_type === "post").length;

  const btnStyle = (active) => ({
    padding: "6px 14px",
    borderRadius: 6,
    border: "1px solid",
    borderColor: active ? "rgba(97, 218, 251, 0.4)" : "rgba(255,255,255,0.08)",
    background: active ? "rgba(97, 218, 251, 0.08)" : "transparent",
    color: active ? "#61dafb" : "#a1a1aa",
    fontSize: 12,
    fontWeight: 500,
    cursor: "pointer",
    transition: "all 0.15s ease",
  });

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "#09090b",
        color: "#e4e4e7",
        fontFamily:
          "'Instrument Sans', 'DM Sans', -apple-system, BlinkMacSystemFont, sans-serif",
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: "28px 28px 20px",
          borderBottom: "1px solid rgba(255,255,255,0.06)",
          background:
            "linear-gradient(180deg, rgba(97, 218, 251, 0.03) 0%, transparent 100%)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
          <div
            style={{
              width: 8,
              height: 8,
              borderRadius: "50%",
              background: "#10b981",
              boxShadow: "0 0 8px rgba(16,185,129,0.5)",
            }}
          />
          <span style={{ fontSize: 11, color: "#71717a", fontWeight: 500, letterSpacing: "0.05em", textTransform: "uppercase" }}>
            Live Feed
          </span>
        </div>
        <h1
          style={{
            fontSize: 22,
            fontWeight: 700,
            margin: "0 0 4px",
            letterSpacing: "-0.02em",
          }}
        >
          <span style={{ color: "#61dafb" }}>React Native</span>{" "}
          Opportunities
        </h1>
        <p style={{ fontSize: 13, color: "#71717a", margin: 0 }}>
          {data.metadata.total_results} curated results · {jobCount} jobs · {postCount} posts · India excluded
        </p>
      </div>

      {/* Controls */}
      <div
        style={{
          padding: "14px 28px",
          display: "flex",
          gap: 10,
          alignItems: "center",
          flexWrap: "wrap",
          borderBottom: "1px solid rgba(255,255,255,0.04)",
        }}
      >
        <div
          style={{
            flex: 1,
            minWidth: 200,
            display: "flex",
            alignItems: "center",
            gap: 8,
            background: "rgba(255,255,255,0.03)",
            border: "1px solid rgba(255,255,255,0.08)",
            borderRadius: 8,
            padding: "0 12px",
          }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#71717a" strokeWidth="2">
            <circle cx="11" cy="11" r="8" />
            <path d="M21 21l-4.35-4.35" />
          </svg>
          <input
            type="text"
            placeholder="Filter results..."
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            style={{
              flex: 1,
              background: "transparent",
              border: "none",
              outline: "none",
              color: "#e4e4e7",
              fontSize: 13,
              padding: "8px 0",
              fontFamily: "inherit",
            }}
          />
        </div>

        <div style={{ display: "flex", gap: 6 }}>
          {["all", "job", "post"].map((t) => (
            <button key={t} onClick={() => setFilterType(t)} style={btnStyle(filterType === t)}>
              {t === "all" ? "All" : t === "job" ? `Jobs (${jobCount})` : `Posts (${postCount})`}
            </button>
          ))}
        </div>

        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value)}
          style={{
            padding: "6px 10px",
            borderRadius: 6,
            border: "1px solid rgba(255,255,255,0.08)",
            background: "#18181b",
            color: "#a1a1aa",
            fontSize: 12,
            cursor: "pointer",
            outline: "none",
          }}
        >
          <option value="relevance">Sort: Relevance</option>
          <option value="newest">Sort: Newest</option>
        </select>
      </div>

      {/* Results */}
      <div>
        {filtered.length === 0 ? (
          <div style={{ textAlign: "center", padding: "60px 20px", color: "#555" }}>
            <p style={{ fontSize: 15 }}>No results match your filters</p>
          </div>
        ) : (
          filtered.map((item, idx) => (
            <OpportunityCard key={item.url} item={item} index={idx} />
          ))
        )}
      </div>

      {/* Footer */}
      <div
        style={{
          padding: "16px 28px",
          borderTop: "1px solid rgba(255,255,255,0.04)",
          display: "flex",
          justifyContent: "space-between",
          fontSize: 11,
          color: "#3f3f46",
        }}
      >
        <span>rn_linkedin_scraper.py · India filter active</span>
        <span>
          {filtered.length} of {data.metadata.total_results} shown
        </span>
      </div>
    </div>
  );
}
