TOKEN_BUDGET_PROFILES = {
    "economy": {
        "phase1": 500,
        "phase2": 400,
        "phase3": 800,
        "chat": 400,
    },
    "balanced": {
        "phase1": 1000,
        "phase2": 700,
        "phase3": 2000,
        "chat": 800,
    },
    "performance": {
        "phase1": 1500,
        "phase2": 1000,
        "phase3": 3000,
        "chat": 1200,
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
