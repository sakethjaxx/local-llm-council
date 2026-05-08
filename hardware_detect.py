import psutil


def _build_config(architect_model: str, security_model: str, perf_model: str, chairman_model: str) -> dict:
    return {
        "architect": {
            "label": "Lead Architect",
            "model": architect_model,
            "color": "#4D6BFE",
            "icon": "🐋",
            "persona": "You are the Lead Architect. Focus on SOLID principles, design patterns, maintainability, and code structure. Favor pragmatic, local-first solutions and call out unnecessary complexity.",
        },
        "security": {
            "label": "Security Auditor",
            "model": security_model,
            "color": "#FF4444",
            "icon": "🛡️",
            "persona": "You are the Senior Security Auditor. Focus strictly on OWASP vulnerabilities, injection flaws, unsafe defaults, and exposure risk. Prefer defenses that work in local self-hosted deployments.",
        },
        "perf": {
            "label": "Performance Eng",
            "model": perf_model,
            "color": "#00FF00",
            "icon": "⚡",
            "persona": "You are the Performance Engineer. Focus on algorithmic cost, memory pressure, context bloat, and latency. Optimize for hardware-constrained local inference.",
        },
        "chairman": {
            "label": "Chairman",
            "model": chairman_model,
            "color": "#F5C842",
            "icon": "👑",
            "persona": "You are the Chairman. Synthesize the council and make a final verdict. Prefer recommendations that preserve free, open-weight, local execution.",
        },
    }


def get_hardware_suggestion():
    total_ram_gb = psutil.virtual_memory().total / (1024 ** 3)

    tier_name = "Tier 1: < 10GB (Small Local Models)"
    config = _build_config(
        architect_model="ollama/qwen2.5:3b",
        security_model="ollama/gemma2:2b",
        perf_model="ollama/llama3.2:3b",
        chairman_model="ollama/qwen2.5:3b",
    )
    recommended_pull = [
        "ollama pull qwen2.5:3b",
        "ollama pull gemma2:2b",
        "ollama pull llama3.2:3b",
    ]

    if total_ram_gb >= 40:
        tier_name = "Tier 4: > 40GB (Large Local Models)"
        config = _build_config(
            architect_model="ollama/qwen2.5:32b",
            security_model="ollama/deepseek-r1:32b",
            perf_model="ollama/llama3.1:70b",
            chairman_model="ollama/qwen2.5:32b",
        )
        recommended_pull = [
            "ollama pull qwen2.5:32b",
            "ollama pull deepseek-r1:32b",
            "ollama pull llama3.1:70b",
        ]
    elif total_ram_gb >= 20:
        tier_name = "Tier 3: 20-40GB (Strong 7B-14B Local Models)"
        config = _build_config(
            architect_model="ollama/qwen2.5:14b",
            security_model="ollama/deepseek-r1:14b",
            perf_model="ollama/llama3.1:8b",
            chairman_model="ollama/qwen2.5:14b",
        )
        recommended_pull = [
            "ollama pull qwen2.5:14b",
            "ollama pull deepseek-r1:14b",
            "ollama pull llama3.1:8b",
        ]
    elif total_ram_gb >= 10:
        tier_name = "Tier 2: 10-20GB (Reliable 7B-8B Local Models)"
        config = _build_config(
            architect_model="ollama/qwen2.5:7b",
            security_model="ollama/gemma2:9b",
            perf_model="ollama/llama3.1:8b",
            chairman_model="ollama/qwen2.5:7b",
        )
        recommended_pull = [
            "ollama pull qwen2.5:7b",
            "ollama pull gemma2:9b",
            "ollama pull llama3.1:8b",
        ]

    return {
        "ram_gb": round(total_ram_gb, 1),
        "tier_name": tier_name,
        "mode": "free-local-open-weights",
        "provider": "ollama",
        "config": config,
        "recommended_pull": recommended_pull,
    }


def get_default_council_config() -> dict:
    return get_hardware_suggestion()["config"]
