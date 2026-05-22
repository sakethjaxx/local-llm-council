TOKEN_BUDGET_PROFILES = {
    "economy": {
        "phase1": 300,
        "phase2": 250,
        "phase3": 500,
        "chat": 300,
    },
    "balanced": {
        "phase1": 600,
        "phase2": 400,
        "phase3": 1200,
        "chat": 600,
    },
    "performance": {
        "phase1": 900,
        "phase2": 650,
        "phase3": 1600,
        "chat": 900,
    },
}


DEFAULT_TOKEN_BUDGET_PROFILE = "balanced"


def normalize_token_budget_profile(profile: str | None) -> str:
    if not profile:
        return DEFAULT_TOKEN_BUDGET_PROFILE
    normalized = str(profile).strip().lower()
    if normalized not in TOKEN_BUDGET_PROFILES:
        return DEFAULT_TOKEN_BUDGET_PROFILE
    return normalized


def token_budget_for(profile: str | None) -> dict[str, int]:
    return TOKEN_BUDGET_PROFILES[normalize_token_budget_profile(profile)].copy()
