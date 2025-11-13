"""
Database Schemas for Mental Wellness App

Each Pydantic model represents a MongoDB collection.
Collection name = lowercase of class name (e.g., MoodLog -> "moodlog").
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import datetime

# Users may be anonymous; we use anonymous_id to associate local device data with backend
class UserProfile(BaseModel):
    anonymous_id: str = Field(..., description="Device-scoped anonymous identifier")
    name: Optional[str] = Field(None, description="Display name if provided")
    language: Literal['en', 'ta'] = Field('en', description="Language preference: en (English) or ta (Tamil)")
    goals: List[Literal['stress', 'focus', 'sleep']] = Field(default_factory=list)
    notify_enabled: bool = Field(True)
    notify_times: List[str] = Field(default_factory=lambda: ['09:00'])
    privacy_anonymous_mode: bool = Field(True, description="If true, treat as anonymous and avoid storing sensitive text")
    reduced_motion: bool = Field(False)

class MoodLog(BaseModel):
    anonymous_id: str
    mood: Literal[1,2,3,4,5] = Field(..., description="1=Very low, 5=Joyful")
    emoji: Literal['😞','😐','🙂','😊','😁']
    note: Optional[str] = Field(None, max_length=200)
    tags: List[Literal['work','family','sleep','food']] = Field(default_factory=list)
    logged_at: datetime = Field(default_factory=datetime.utcnow)

class SuggestionEngagement(BaseModel):
    anonymous_id: str
    suggestion_id: str
    action: Literal['viewed','completed','favorited']
    reason: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

class JournalEntry(BaseModel):
    anonymous_id: str
    text: str = Field(..., max_length=1500)
    mood_at_time: Optional[int] = Field(None, ge=1, le=5)
    voice_note_url: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

class AppEvent(BaseModel):
    anonymous_id: str
    event: Literal['mood_logged','suggestion_viewed','suggestion_completed','journal_saved','onboarding_completed','daily_active_user','retention7','retention30']
    meta: Optional[dict] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
