"""Process defaults that must be set before optional SDK imports."""

import os


# LiteLLM otherwise fetches its pricing map from GitHub during import. The
# bundled map is sufficient for this app's capability registry and keeps the
# default local-first server boot fully offline.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
