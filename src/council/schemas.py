from typing import List, Literal, Optional
from pydantic import BaseModel, Field

from budget_profiles import DEFAULT_TOKEN_BUDGET_PROFILE
from main_routes_helper import DEFAULT_REVIEW_FILE_BUDGET


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str = Field(max_length=20_000)


class ChatRequest(BaseModel):
    member_id: str = Field(min_length=1, max_length=64)
    messages: List[ChatMessage] = Field(min_length=1, max_length=100)
    council_config: Optional[dict] = None
    token_budget_profile: str = DEFAULT_TOKEN_BUDGET_PROFILE


class ConfigCheckRequest(BaseModel):
    council_config: Optional[dict] = None
    attachment_names: List[str] = Field(default_factory=list, max_length=200)


class FeedbackRequest(BaseModel):
    action_index: int = Field(ge=0, le=10_000)
    rating: Literal["thumbs_up", "thumbs_down", "ignored"]
    note: str = Field(default="", max_length=10_000)


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
