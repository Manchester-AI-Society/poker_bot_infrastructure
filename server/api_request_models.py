from typing import List, Literal, Optional

from pydantic import BaseModel, Field

ActionType = Literal["fold", "check", "call", "bet", "raise", "raise_to"]
EndMatchMode = Literal["terminate_as_is", "refund_committed"]


class CreateMatchRequest(BaseModel):
    player_ids: List[str]
    starting_stack: int = Field(default=1000, ge=1)
    small_blind: int = Field(default=10, ge=1)
    big_blind: int = Field(default=20, ge=2)
    turn_timeout_seconds: int = Field(default=15, ge=2, le=120)
    event_log_limit: int = Field(default=2000, ge=100, le=100000)
    max_hands: Optional[int] = Field(default=None, ge=1)
    wait_for_players: bool = True


class SubmitActionRequest(BaseModel):
    action: ActionType
    amount: Optional[int] = Field(default=None, ge=1)
    turn_id: Optional[int] = Field(default=None, ge=1)


class PauseMatchRequest(BaseModel):
    reason: Optional[str] = None


class ResumeMatchRequest(BaseModel):
    reason: Optional[str] = None


class EndMatchRequest(BaseModel):
    reason: Optional[str] = None
    mode: EndMatchMode = "terminate_as_is"


class CreatePlayerRequest(BaseModel):
    player_id: str = Field(min_length=1)
    api_key: Optional[str] = Field(default=None, min_length=8)


class RotatePlayerKeyRequest(BaseModel):
    api_key: Optional[str] = Field(default=None, min_length=8)
