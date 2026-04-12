from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ConversationCreate(BaseModel):
    workspace_id: int
    title: str | None = Field(default=None, max_length=255)


class ConversationUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class ConversationResponse(BaseModel):
    id: int
    workspace_id: int
    title: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
