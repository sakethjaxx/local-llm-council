"""Process defaults that must be set before optional SDK imports."""

import os
import warnings

# LiteLLM otherwise fetches its pricing map from GitHub during import. The
# bundled map is sufficient for this app's capability registry and keeps the
# default local-first server boot fully offline.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

# Suppress upstream third-party deprecation & serializer warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*Pydantic serializer warnings.*")
warnings.filterwarnings("ignore", message=".*PydanticDeprecatedSince20.*")
warnings.filterwarnings("ignore", message=".*builtin type SwigPy.*")

try:
    import litellm
    litellm.suppress_debug_info = True
    litellm.set_verbose = False
except ImportError:
    pass
