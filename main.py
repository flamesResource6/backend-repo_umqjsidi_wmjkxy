import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import db, create_document, get_documents
from schemas import UserProfile, MoodLog, JournalEntry, SuggestionEngagement, AppEvent

app = FastAPI(title="Mental Wellness API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {"message": "Mental Wellness API running"}


# ---------- Profiles ----------
class ProfileUpdate(BaseModel):
    anonymous_id: str
    name: Optional[str] = None
    language: Optional[str] = None
    goals: Optional[List[str]] = None
    notify_enabled: Optional[bool] = None
    notify_times: Optional[List[str]] = None
    privacy_anonymous_mode: Optional[bool] = None
    reduced_motion: Optional[bool] = None


@app.post("/api/profile")
def upsert_profile(payload: UserProfile):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    # Upsert based on anonymous_id
    data = payload.model_dump()
    data["updated_at"] = datetime.now(timezone.utc)
    existing = db["userprofile"].find_one({"anonymous_id": payload.anonymous_id})
    if existing:
        db["userprofile"].update_one({"_id": existing["_id"]}, {"$set": data})
        return {"status": "updated"}
    else:
        create_document("userprofile", data)
        return {"status": "created"}


@app.get("/api/profile")
def get_profile(anonymous_id: str = Query(...)):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    doc = db["userprofile"].find_one({"anonymous_id": anonymous_id}, {"_id": 0})
    if not doc:
        # Return minimal default
        return {
            "anonymous_id": anonymous_id,
            "language": "en",
            "goals": [],
            "notify_enabled": True,
            "notify_times": ["09:00"],
            "privacy_anonymous_mode": True,
            "reduced_motion": False,
        }
    return doc


# ---------- Mood Logs ----------
@app.post("/api/moodlog")
def add_mood_log(payload: MoodLog):
    # Basic privacy guard: trim note length, optional redaction could be added
    data = payload.model_dump()
    try:
        _id = create_document("moodlog", data)
        # analytics event
        create_document("appevent", {
            "anonymous_id": payload.anonymous_id,
            "event": "mood_logged",
            "meta": {"mood": payload.mood, "tags": payload.tags},
            "created_at": datetime.now(timezone.utc)
        })
        return {"id": _id, "status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/moodlog")
def list_mood_logs(anonymous_id: str, days: int = 7):
    since = datetime.utcnow() - timedelta(days=days)
    items = db["moodlog"].find({
        "anonymous_id": anonymous_id,
        "logged_at": {"$gte": since}
    }, {"_id": 0}).sort("logged_at", 1)
    return list(items)


# ---------- Journal ----------
@app.post("/api/journal")
def add_journal(payload: JournalEntry):
    data = payload.model_dump()
    if len(data.get("text", "").strip()) == 0:
        raise HTTPException(status_code=400, detail="Text required")
    _id = create_document("journalentry", data)
    create_document("appevent", {
        "anonymous_id": payload.anonymous_id,
        "event": "journal_saved",
        "meta": None,
        "created_at": datetime.now(timezone.utc)
    })
    return {"id": _id, "status": "ok"}


@app.get("/api/journal")
def list_journal(anonymous_id: str, limit: int = 20):
    items = db["journalentry"].find({"anonymous_id": anonymous_id}, {"_id": 0}).sort("created_at", -1).limit(limit)
    return list(items)


# ---------- Suggestions ----------
SUGGESTION_LIBRARY = [
    {"id": "breath-2", "title": "Try this quick breathing reset", "duration": 2, "type": "breathing"},
    {"id": "meditate-5", "title": "Mini meditation", "duration": 5, "type": "meditation"},
    {"id": "walk-5", "title": "Micro-walk", "duration": 5, "type": "walk"},
    {"id": "affirm-1", "title": "Affirmation card", "duration": 1, "type": "affirmation"},
]


def compute_insights(anonymous_id: str, days: int = 7):
    since = datetime.utcnow() - timedelta(days=days)
    logs = list(db["moodlog"].find({
        "anonymous_id": anonymous_id,
        "logged_at": {"$gte": since}
    }))
    if not logs:
        return {
            "avg_mood": None,
            "entries": 0,
            "streak": 0,
            "by_day": [],
        }
    # Average
    avg = round(sum(l.get("mood", 0) for l in logs) / len(logs), 2)
    # Streak: consecutive days with at least one entry
    days_set = {datetime.fromtimestamp(int(l["logged_at"].timestamp())).date() for l in logs}
    streak = 0
    today = datetime.utcnow().date()
    d = today
    while d in days_set:
        streak += 1
        d = d - timedelta(days=1)
    # By day average
    by = {}
    for l in logs:
        d = datetime.fromtimestamp(int(l["logged_at"].timestamp())).date().isoformat()
        by.setdefault(d, []).append(l["mood"])
    by_day = [{"date": k, "avg": round(sum(v)/len(v), 2)} for k, v in sorted(by.items())]
    return {"avg_mood": avg, "entries": len(logs), "streak": streak, "by_day": by_day}


@app.get("/api/suggestions")
def get_suggestions(anonymous_id: str, days: int = 7):
    insights = compute_insights(anonymous_id, days)
    reason = None
    picks = []
    if insights["avg_mood"] is None:
        picks = SUGGESTION_LIBRARY[:2]
        reason = "Suggested to help you start your routine"
    else:
        # Rule-based fallback
        if insights["avg_mood"] < 3 and insights["entries"] >= 3:
            picks = [SUGGESTION_LIBRARY[0], SUGGESTION_LIBRARY[1]]
            reason = "Suggested because your average mood has been low this week"
        else:
            picks = [SUGGESTION_LIBRARY[2], SUGGESTION_LIBRARY[3]]
            reason = "Suggested based on your recent logs"
    return {"reason": reason, "items": picks, "insights": insights}


@app.post("/api/engagement")
def track_engagement(payload: SuggestionEngagement):
    _id = create_document("suggestionengagement", payload)
    # Mirror to analytics
    if payload.action in ("viewed", "completed"):
        create_document("appevent", {
            "anonymous_id": payload.anonymous_id,
            "event": f"suggestion_{payload.action}",
            "meta": {"suggestion_id": payload.suggestion_id},
            "created_at": datetime.now(timezone.utc)
        })
    return {"id": _id, "status": "ok"}


# ---------- Insights & Export ----------
@app.get("/api/insights")
def insights(anonymous_id: str, range: str = "7d"):
    days = 7 if range == "7d" else 30
    data = compute_insights(anonymous_id, days)
    # Simple AI summary template
    summary = []
    actions = []
    if data["avg_mood"] is None:
        summary.append("No logs yet. Start with a 2-minute breathing reset.")
        actions.append("Set a daily reminder at a calm time.")
    else:
        if data["avg_mood"] < 3:
            summary.append("Mood has been on the lower side recently.")
            actions.append("Try a daily 5-minute mini meditation for 3 days.")
        else:
            summary.append("You're maintaining a stable mood trend.")
            actions.append("Keep up the short check-ins and a micro-walk.")
        if data["streak"] >= 3:
            summary.append(f"Nice streak: {data['streak']} days in a row.")
    return {"kpis": data, "ai_summary": summary, "suggested_actions": actions}


@app.get("/api/export")
def export_data(anonymous_id: str):
    logs = list(db["moodlog"].find({"anonymous_id": anonymous_id}, {"_id": 0}))
    journal = list(db["journalentry"].find({"anonymous_id": anonymous_id}, {"_id": 0}))
    profile = db["userprofile"].find_one({"anonymous_id": anonymous_id}, {"_id": 0}) or {}
    return {"profile": profile, "mood_logs": logs, "journal": journal}


# ---------- Analytics ----------
@app.post("/api/event")
def track_event(evt: AppEvent):
    _id = create_document("appevent", evt)
    return {"id": _id, "status": "ok"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
    return response


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
