import litellm
import re
from pydantic import BaseModel
from typing import Dict

class PersonaConfig(BaseModel):
    label: str
    model: str
    color: str
    icon: str
    persona: str

class SwarmConfig(BaseModel):
    experts: Dict[str, PersonaConfig]


def _supports_response_format(model: str) -> bool:
    return not model.startswith("ollama/")


def _extract_json_block(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, re.DOTALL)
        if match:
            return match.group(1).strip()
    return raw

async def generate_swarm(topic: str, base_model: str) -> dict:
    prompt = f"""
    You are an intelligent swarm router. Given the topic, generate exactly 3 highly specialized personas that are perfectly suited to analyze it.
    Return valid JSON with a top-level 'experts' object mapping simple IDs to their config.
    For each expert, the 'model' field MUST be set to exactly: "{base_model}"
    Topic: {topic}
    """
    print("\n[🌀 Swarm Router] Determining optimal personas...")
    try:
        completion_kwargs = {
            "model": base_model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 800,
        }
        if _supports_response_format(base_model):
            completion_kwargs["response_format"] = SwarmConfig

        resp = await litellm.acompletion(
            **completion_kwargs
        )
        content = resp.choices[0].message.content
        swarm = SwarmConfig.model_validate_json(_extract_json_block(content))
        return {k: v.model_dump() for k, v in swarm.experts.items()}
    except Exception as e:
        print(f"[❌ Swarm Router Failed]: {e}")
        return None
