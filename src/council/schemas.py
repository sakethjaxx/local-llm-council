from typing import List, Literal, Optional
from pydantic import BaseModel

from budget_profiles import DEFAULT_TOKEN_BUDGET_PROFILE
from main_routes_helper import DEFAULT_REVIEW_FILE_BUDGET


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    member_id: str
    messages: List[ChatMessage]
    council_config: Optional[dict] = None
    token_budget_profile: str = DEFAULT_TOKEN_BUDGET_PROFILE


class ConfigCheckRequest(BaseModel):
    council_config: Optional[dict] = None
    attachment_names: List[str] = []


class FeedbackRequest(BaseModel):
    action_index: int
    rating: Literal["thumbs_up", "thumbs_down", "ignored"]
    note: str = ""


class FolderIngestRequest(BaseModel):
    folder_path: str
    max_files: Optional[int] = 50


class ReviewProjectRequest(BaseModel):
    path: str = "."
    deep_debate: bool = False
    council_config: Optional[dict] = None
    token_budget_profile: str = DEFAULT_TOKEN_BUDGET_PROFILE
    max_files: int = DEFAULT_REVIEW_FILE_BUDGET


class DemoLoadRequest(BaseModel):
    scenario_id: str
