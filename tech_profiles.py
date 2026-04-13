"""
Tech profiles for the job scraper.
Each profile defines search queries, filter keywords, and scoring signals
for a specific technology stack.
"""

TECH_PROFILES = {
    "react_native": {
        "label": "React Native",
        "color": "#61dafb",
        "job_queries": [
            '"react native" developer remote',
            '"react native" engineer remote',
            '"react native" mobile developer remote',
            '"react native" senior developer remote',
            '"react native" lead remote',
            '"react native" freelance remote',
            '"react native" contract remote',
            'expo "react native" remote',
            '"mobile engineer" "react native" remote',
        ],
        "post_queries": [
            '"react native" hiring remote',
            '"react native" we are hiring remote',
            '"react native" developer remote',
            '"react native" open role remote',
            '"react native" remote opportunity',
            '"expo" "react native" mobile remote',
        ],
        "filter_keywords": [
            "react native", "react-native", "reactnative", "expo",
            "mobile developer", "mobile engineer", "mobile development",
            "mobile app", "cross-platform", "cross platform",
            "ios and android", "android and ios", "ios/android", "android/ios",
        ],
        "scoring_signals": {
            "react native": 15, "react-native": 15, "reactnative": 15,
            "expo": 12, "mobile developer": 10, "mobile engineer": 10,
            "mobile development": 8, "mobile app": 8,
            "cross-platform": 6, "cross platform": 6,
            "ios and android": 6, "android and ios": 6,
            "typescript": 2, "javascript": 1,
        },
    },
    "react": {
        "label": "React",
        "color": "#61dafb",
        "job_queries": [
            '"react" frontend developer remote',
            '"react" engineer remote',
            '"react.js" developer remote',
            '"react" senior frontend remote',
            '"react" full stack developer remote',
            '"next.js" developer remote',
            '"react" "typescript" developer remote',
        ],
        "post_queries": [
            '"react" frontend hiring remote',
            '"react" developer we are hiring remote',
            '"next.js" hiring remote',
            '"react" open role remote',
        ],
        "filter_keywords": [
            "react", "react.js", "reactjs", "next.js", "nextjs",
            "frontend developer", "front-end developer", "front end",
            "full stack", "fullstack", "ui developer", "ui engineer",
        ],
        "scoring_signals": {
            "react": 12, "react.js": 12, "reactjs": 12,
            "next.js": 10, "nextjs": 10,
            "frontend": 8, "front-end": 8, "front end": 8,
            "full stack": 6, "fullstack": 6,
            "typescript": 4, "javascript": 3,
            "tailwind": 2, "redux": 2,
        },
    },
    "python": {
        "label": "Python",
        "color": "#3776ab",
        "job_queries": [
            '"python" developer remote',
            '"python" engineer remote',
            '"python" backend developer remote',
            '"python" senior developer remote',
            '"django" developer remote',
            '"fastapi" developer remote',
            '"python" data engineer remote',
            '"python" machine learning remote',
        ],
        "post_queries": [
            '"python" developer hiring remote',
            '"python" we are hiring remote',
            '"django" hiring remote',
            '"python" open role remote',
        ],
        "filter_keywords": [
            "python", "django", "fastapi", "flask",
            "data engineer", "data scientist", "machine learning",
            "backend developer", "back-end developer", "back end",
            "ml engineer", "ai engineer",
        ],
        "scoring_signals": {
            "python": 15, "django": 10, "fastapi": 10, "flask": 8,
            "data engineer": 8, "data scientist": 8,
            "machine learning": 8, "ml engineer": 8,
            "backend": 6, "back-end": 6,
            "pandas": 3, "numpy": 3, "pytorch": 4, "tensorflow": 4,
        },
    },
    "node": {
        "label": "Node.js",
        "color": "#339933",
        "job_queries": [
            '"node.js" developer remote',
            '"nodejs" engineer remote',
            '"node" backend developer remote',
            '"express" developer remote',
            '"nestjs" developer remote',
            '"node.js" senior developer remote',
            '"node" full stack remote',
        ],
        "post_queries": [
            '"node.js" hiring remote',
            '"nodejs" developer hiring remote',
            '"node" backend open role remote',
        ],
        "filter_keywords": [
            "node.js", "nodejs", "node", "express", "nestjs", "nest.js",
            "backend developer", "back-end", "full stack", "fullstack",
            "server-side", "api developer",
        ],
        "scoring_signals": {
            "node.js": 15, "nodejs": 15, "express": 10, "nestjs": 10,
            "backend": 6, "full stack": 6, "fullstack": 6,
            "typescript": 4, "javascript": 3,
            "mongodb": 3, "postgresql": 3,
        },
    },
    "golang": {
        "label": "Go / Golang",
        "color": "#00add8",
        "job_queries": [
            '"golang" developer remote',
            '"go" backend developer remote',
            '"golang" engineer remote',
            '"go" senior developer remote',
            '"golang" senior engineer remote',
            '"go" distributed systems remote',
        ],
        "post_queries": [
            '"golang" hiring remote',
            '"golang" developer open role remote',
            '"go" backend hiring remote',
        ],
        "filter_keywords": [
            "golang", "go developer", "go engineer", "go programming",
            "backend developer", "distributed systems",
            "microservices", "cloud infrastructure",
        ],
        "scoring_signals": {
            "golang": 15, "go developer": 12, "go engineer": 12,
            "distributed systems": 8, "microservices": 6,
            "kubernetes": 4, "docker": 3, "grpc": 4,
            "backend": 6, "cloud": 3,
        },
    },
    "rust": {
        "label": "Rust",
        "color": "#dea584",
        "job_queries": [
            '"rust" developer remote',
            '"rust" engineer remote',
            '"rust" systems developer remote',
            '"rust" senior engineer remote',
            '"rust" backend developer remote',
        ],
        "post_queries": [
            '"rust" developer hiring remote',
            '"rust" engineer open role remote',
            '"rust" we are hiring remote',
        ],
        "filter_keywords": [
            "rust", "rustlang", "rust developer", "rust engineer",
            "systems programming", "systems developer",
            "embedded", "low-level", "performance",
        ],
        "scoring_signals": {
            "rust": 15, "rustlang": 15,
            "systems programming": 8, "embedded": 6,
            "webassembly": 5, "wasm": 5,
            "backend": 4, "performance": 3,
        },
    },
    "typescript": {
        "label": "TypeScript",
        "color": "#3178c6",
        "job_queries": [
            '"typescript" developer remote',
            '"typescript" engineer remote',
            '"typescript" full stack remote',
            '"typescript" senior developer remote',
            '"typescript" backend developer remote',
        ],
        "post_queries": [
            '"typescript" developer hiring remote',
            '"typescript" open role remote',
            '"typescript" we are hiring remote',
        ],
        "filter_keywords": [
            "typescript", "ts developer",
            "full stack", "fullstack", "frontend", "backend",
        ],
        "scoring_signals": {
            "typescript": 15, "full stack": 8, "fullstack": 8,
            "frontend": 6, "backend": 6,
            "react": 4, "node": 4, "angular": 4, "vue": 4,
        },
    },
    "java": {
        "label": "Java",
        "color": "#ed8b00",
        "job_queries": [
            '"java" developer remote',
            '"java" engineer remote',
            '"java" senior developer remote',
            '"spring boot" developer remote',
            '"java" backend developer remote',
            '"kotlin" developer remote',
        ],
        "post_queries": [
            '"java" developer hiring remote',
            '"spring boot" hiring remote',
            '"java" open role remote',
        ],
        "filter_keywords": [
            "java", "spring boot", "spring", "kotlin",
            "backend developer", "microservices",
            "jvm", "enterprise",
        ],
        "scoring_signals": {
            "java": 15, "spring boot": 10, "spring": 8, "kotlin": 10,
            "microservices": 6, "backend": 6,
            "jvm": 4, "hibernate": 3,
        },
    },
    "ios": {
        "label": "iOS / Swift",
        "color": "#f05138",
        "job_queries": [
            '"ios" developer remote',
            '"swift" developer remote',
            '"ios" engineer remote',
            '"swiftui" developer remote',
            '"ios" senior developer remote',
        ],
        "post_queries": [
            '"ios" developer hiring remote',
            '"swift" hiring remote',
            '"ios" open role remote',
        ],
        "filter_keywords": [
            "ios", "swift", "swiftui", "uikit", "objective-c",
            "apple", "iphone", "ipad",
            "mobile developer", "mobile engineer",
        ],
        "scoring_signals": {
            "ios": 15, "swift": 15, "swiftui": 12, "uikit": 10,
            "objective-c": 8, "mobile developer": 8,
            "mobile engineer": 8, "apple": 4,
        },
    },
    "android": {
        "label": "Android / Kotlin",
        "color": "#3ddc84",
        "job_queries": [
            '"android" developer remote',
            '"kotlin" android developer remote',
            '"android" engineer remote',
            '"jetpack compose" developer remote',
            '"android" senior developer remote',
        ],
        "post_queries": [
            '"android" developer hiring remote',
            '"kotlin" android hiring remote',
            '"android" open role remote',
        ],
        "filter_keywords": [
            "android", "kotlin", "jetpack compose", "jetpack",
            "mobile developer", "mobile engineer",
        ],
        "scoring_signals": {
            "android": 15, "kotlin": 12, "jetpack compose": 10,
            "mobile developer": 8, "mobile engineer": 8,
            "java": 3, "gradle": 2,
        },
    },
    "devops": {
        "label": "DevOps / SRE",
        "color": "#326ce5",
        "job_queries": [
            '"devops" engineer remote',
            '"site reliability" engineer remote',
            '"sre" engineer remote',
            '"platform engineer" remote',
            '"cloud engineer" remote',
            '"devops" senior engineer remote',
            '"kubernetes" engineer remote',
        ],
        "post_queries": [
            '"devops" hiring remote',
            '"sre" hiring remote',
            '"platform engineer" hiring remote',
        ],
        "filter_keywords": [
            "devops", "sre", "site reliability", "platform engineer",
            "cloud engineer", "infrastructure", "kubernetes", "k8s",
            "terraform", "aws", "gcp", "azure", "ci/cd", "cicd",
        ],
        "scoring_signals": {
            "devops": 15, "sre": 15, "site reliability": 12,
            "platform engineer": 12, "cloud engineer": 10,
            "kubernetes": 8, "terraform": 8, "docker": 6,
            "aws": 4, "gcp": 4, "azure": 4, "ci/cd": 4,
        },
    },
    "data": {
        "label": "Data Engineering",
        "color": "#e535ab",
        "job_queries": [
            '"data engineer" remote',
            '"data scientist" remote',
            '"analytics engineer" remote',
            '"machine learning" engineer remote',
            '"data" senior engineer remote',
            '"dbt" "data" engineer remote',
        ],
        "post_queries": [
            '"data engineer" hiring remote',
            '"data scientist" hiring remote',
            '"ml engineer" hiring remote',
        ],
        "filter_keywords": [
            "data engineer", "data scientist", "analytics engineer",
            "machine learning", "ml engineer", "ai engineer",
            "data pipeline", "etl", "dbt", "spark", "airflow",
            "big data", "data warehouse",
        ],
        "scoring_signals": {
            "data engineer": 15, "data scientist": 15,
            "analytics engineer": 12, "machine learning": 12,
            "ml engineer": 12, "ai engineer": 10,
            "spark": 6, "airflow": 6, "dbt": 6,
            "python": 4, "sql": 4,
        },
    },
}


def get_profile(tech_id: str) -> dict:
    """Get a tech profile by ID, or None."""
    return TECH_PROFILES.get(tech_id)


def get_all_profiles() -> dict:
    """Return all profiles with their IDs."""
    return {k: {"id": k, **v} for k, v in TECH_PROFILES.items()}


def get_profile_summary() -> list[dict]:
    """Return a lightweight list for the frontend selector."""
    return [
        {"id": k, "label": v["label"], "color": v["color"]}
        for k, v in TECH_PROFILES.items()
    ]
