DEMO_PRESETS = [
    {
        "id": "fast",
        "label": "Fast Triage",
        "description": "Low-latency council for a controlled architecture or product brief demo.",
        "topic": "Review this local-first AI council project for architectural clarity, practical risks, and the next three improvements to ship.",
        "deep_debate": False,
        "dynamic_swarm": False,
        "config": {
            "architect": {
                "label": "Lead Architect",
                "model": "ollama/qwen2.5:3b",
                "color": "#4D6BFE",
                "icon": "🐋",
                "persona": "You are the Lead Architect. Focus on architecture, maintainability, and simplification.",
            },
            "security": {
                "label": "Security Auditor",
                "model": "ollama/gemma2:2b",
                "color": "#FF4444",
                "icon": "🛡️",
                "persona": "You are the Security Auditor. Focus on unsafe defaults, data exposure, and operational risk.",
            },
            "perf": {
                "label": "Performance Eng",
                "model": "ollama/llama3.2:3b",
                "color": "#00A76F",
                "icon": "⚡",
                "persona": "You are the Performance Engineer. Focus on latency, memory pressure, and user-perceived responsiveness.",
            },
            "chairman": {
                "label": "Chairman",
                "model": "ollama/qwen2.5:3b",
                "color": "#F5C842",
                "icon": "👑",
                "persona": "You are the Chairman. Synthesize the council into a decisive summary with concrete next steps.",
            },
        },
        "sample_ids": ["architecture-brief"],
    },
    {
        "id": "code",
        "label": "Code Review",
        "description": "Balanced preset for reviewing code, diffs, or design docs with stronger coding models.",
        "topic": "Review the attached code and notes. Identify correctness risks, maintainability issues, and the highest-value refactors before a public demo.",
        "deep_debate": True,
        "dynamic_swarm": False,
        "config": {
            "architect": {
                "label": "Lead Architect",
                "model": "ollama/qwen2.5:7b",
                "color": "#4D6BFE",
                "icon": "🐋",
                "persona": "You are the Lead Architect. Focus on modularity, coupling, and technical debt.",
            },
            "security": {
                "label": "Code Reviewer",
                "model": "ollama/qwen2.5-coder:7b",
                "color": "#C45D1A",
                "icon": "🧩",
                "persona": "You are the Senior Code Reviewer. Focus on bugs, weak assumptions, and code quality.",
            },
            "perf": {
                "label": "Performance Eng",
                "model": "ollama/deepseek-r1:8b",
                "color": "#00A76F",
                "icon": "⚡",
                "persona": "You are the Performance Engineer. Focus on inefficient workflows, context bloat, and runtime tradeoffs.",
            },
            "chairman": {
                "label": "Chairman",
                "model": "ollama/qwen2.5:7b",
                "color": "#F5C842",
                "icon": "👑",
                "persona": "You are the Chairman. Combine code-review findings into a strict go/no-go summary for a demo build.",
            },
        },
        "sample_ids": ["code-review-request", "demo-metrics"],
    },
    {
        "id": "vision",
        "label": "Vision Review",
        "description": "Preset for screenshots, mockups, or product imagery with a vision-capable seat.",
        "topic": "Review the attached product image and supporting notes. Assess clarity, usability, and what should change before showing this to users.",
        "deep_debate": False,
        "dynamic_swarm": False,
        "config": {
            "architect": {
                "label": "UX Strategist",
                "model": "ollama/gemma3:4b",
                "color": "#4D6BFE",
                "icon": "🖼️",
                "persona": "You are the UX Strategist. Focus on visual hierarchy, product clarity, and trust signals.",
            },
            "security": {
                "label": "Risk Reviewer",
                "model": "ollama/qwen2.5:3b",
                "color": "#FF4444",
                "icon": "🛡️",
                "persona": "You are the Risk Reviewer. Focus on misleading UI, unsafe user actions, and confidence gaps.",
            },
            "perf": {
                "label": "Demo Coach",
                "model": "ollama/llama3.2:3b",
                "color": "#00A76F",
                "icon": "🎬",
                "persona": "You are the Demo Coach. Focus on what will land in a live demo and what will confuse the audience.",
            },
            "chairman": {
                "label": "Chairman",
                "model": "ollama/gemma3:4b",
                "color": "#F5C842",
                "icon": "👑",
                "persona": "You are the Chairman. Produce a concise verdict on whether the visual is demo-ready and what to change first.",
            },
        },
        "sample_ids": ["product-demo-notes"],
    },
]


DEMO_SAMPLES = [
    {
        "id": "architecture-brief",
        "label": "Architecture Brief",
        "filename": "architecture_brief.md",
        "content_type": "text/markdown",
        "description": "Short brief describing the local-first council product and expected review goals.",
    },
    {
        "id": "code-review-request",
        "label": "Code Review Request",
        "filename": "code_review_request.md",
        "content_type": "text/markdown",
        "description": "Focused request for a code review style council run.",
    },
    {
        "id": "demo-metrics",
        "label": "Demo Metrics JSON",
        "filename": "demo_metrics.json",
        "content_type": "application/json",
        "description": "Synthetic metrics payload for a realistic attachment demo.",
    },
    {
        "id": "product-demo-notes",
        "label": "Product Demo Notes",
        "filename": "product_demo_notes.md",
        "content_type": "text/markdown",
        "description": "Visual demo checklist and notes to pair with an uploaded screenshot.",
    },
]


def get_demo_catalog() -> dict:
    return {"presets": DEMO_PRESETS, "samples": DEMO_SAMPLES}
