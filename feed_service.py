import os
import json
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import List, Optional

import aiohttp
import uvicorn
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl, EmailStr
from email.message import EmailMessage
import smtplib

# === Configuration / environment ===
DATA_FILE = os.environ.get("OPPORTUNITIES_STORE", "opportunities_store.json")
USERS_FILE = os.environ.get("USERS_STORE", "users_store.json")
TOKEN_EXPIRY_HOURS = int(os.environ.get("TOKEN_EXPIRY_HOURS", "24"))
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")  # used in verification link

# SMTP settings for sending email (set via env)
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")  # e.g., your email
SMTP_PASS = os.environ.get("SMTP_PASS", "")  # app password or SMTP password

# === App setup ===
app = FastAPI(title="OpportunityHub Feed & Auth")

# Allow CORS for local HTML testing; adjust origins in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to your domain when deployed, e.g. ["https://yourdomain.com"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === Data models ===
class Opportunity(BaseModel):
    title: str
    company: Optional[str] = ""
    type: str  # Job, Bursary, Internship, Graduate Program
    category: Optional[str] = ""
    description: Optional[str] = ""
    location: Optional[str] = ""
    salary: Optional[str] = ""
    deadline: Optional[str] = ""
    contact: Optional[HttpUrl] = None  # referral link
    source: Optional[str] = ""
    date: Optional[str] = None
    id: Optional[str] = None

class SignupRequest(BaseModel):
    email: EmailStr

# === Storage helpers ===
def load_json_file(path: str):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return {}

def save_json_file(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_opportunities() -> List[dict]:
    store = load_json_file(DATA_FILE)
    return store.get("items", []) if isinstance(store, dict) else []

def save_opportunities(items: List[dict]):
    save_json_file(DATA_FILE, {"items": items})

def make_id(o: dict) -> str:
    key = (o.get("title", "") + "|" + o.get("company", "") + "|" + o.get("deadline", "")).lower()
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]

def dedupe_and_merge(new_items: List[dict]) -> List[dict]:
    existing = load_opportunities()
    existing_map = {item["id"]: item for item in existing if "id" in item}
    changed = False
    for o in new_items:
        if "id" not in o or not o["id"]:
            o["id"] = make_id(o)
        if o["id"] in existing_map:
            # could update fields here if desired (e.g., newer description)
            continue
        existing_map[o["id"]] = o
        changed = True
    merged = list(existing_map.values())
    if changed:
        save_opportunities(merged)
    return merged

# === RSS / external fetch placeholder ===
async def fetch_from_rss(url: str) -> List[dict]:
    # Stub: implement real parsing if you add RSS sources.
    # Example using feedparser (not included here). Return normalized list of dicts.
    return []

async def refresh_sources():
    # Replace with real feed URLs or APIs
    sources = [
        # e.g. "https://example.com/jobs.rss",
        # "https://someapi.com/bursaries.json"
    ]
    aggregated = []
    for src in sources:
        try:
            if src.endswith(".rss") or src.endswith(".xml"):
                items = await fetch_from_rss(src)
            else:
                async with aiohttp.ClientSession() as session:
                    async with session.get(src, timeout=10) as resp:
                        if resp.status == 200:
                            items = await resp.json()
                        else:
                            items = []
            for it in items:
                normalized = {
                    "title": it.get("title") or "",
                    "company": it.get("company") or "",
                    "type": it.get("type") or "Job",
                    "category": it.get("category") or "",
                    "description": it.get("description") or "",
                    "location": it.get("location") or "",
                    "salary": it.get("salary") or "",
                    "deadline": it.get("deadline") or "",
                    "contact": it.get("apply_link") or it.get("url") or "",
                    "source": src,
                    "date": it.get("date") or datetime.utcnow().strftime("%Y-%m-%d"),
                }
                aggregated.append(normalized)
        except Exception:
            continue
    if aggregated:
        dedupe_and_merge(aggregated)

# === Startup event ===
@app.on_event("startup")
async def startup_event():
    # initial load/refresh from external sources (if any configured)
    await refresh_sources()

# === Opportunity endpoints ===
@app.get("/opportunities", response_model=List[Opportunity])
def get_opportunities():
    store = load_opportunities()
    return store

@app.post("/opportunities", response_model=Opportunity)
def add_opportunity(o: Opportunity):
    data = o.dict()
    data["id"] = make_id(data)
    data["date"] = data.get("date") or datetime.utcnow().strftime("%Y-%m-%d")
    merged = dedupe_and_merge([data])
    stored = next((x for x in merged if x["id"] == data["id"]), data)
    return stored

@app.post("/refresh")
async def manual_refresh():
    await refresh_sources()
    return {"status": "refreshed", "timestamp": datetime.utcnow().isoformat()}

# === Auth/signup/verification helpers ===
def load_users():
    return load_json_file(USERS_FILE)

def save_users(data):
    save_json_file(USERS_FILE, data)

def make_token():
    return secrets.token_urlsafe(32)

def send_verification_email(to_email: str, link: str):
    if not SMTP_USER or not SMTP_PASS:
        raise RuntimeError("SMTP credentials not configured.")
    msg = EmailMessage()
    msg["Subject"] = "Verify your OpportunityHub email"
    msg["From"] = SMTP_USER
    msg["To"] = to_email
    msg.set_content(f"""Hi,

Click the link below to verify your email for OpportunityHub:

{link}

This link expires in {TOKEN_EXPIRY_HOURS} hours.

If you didn't request this, ignore this message.
""")
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.starttls()
        s.login(SMTP_USER, SMTP_PASS)
        s.send_message(msg)

@app.post("/signup")
def signup(req: SignupRequest, background_tasks: BackgroundTasks):
    users = load_users()
    email = req.email.lower()
    token = make_token()
    expiry = (datetime.utcnow() + timedelta(hours=TOKEN_EXPIRY_HOURS)).isoformat()
    users[email] = {
        "verified": False,
        "token": token,
        "token_expiry": expiry
    }
    save_users(users)
    verification_link = f"{BASE_URL}/mod_webjob.html?token={token}"

    def _send():
        try:
            send_verification_email(email, verification_link)
        except Exception:
            # email send failed; nothing to do here, fallback handled below
            pass

    background_tasks.add_task(_send)

    # if SMTP is not set, return link for manual use (development)
    if not SMTP_USER or not SMTP_PASS:
        return {
            "message": "Verification link (email not configured). Use it manually.",
            "verification_link": verification_link
        }
    return {"message": "Verification email sent. Check your inbox."}

@app.get("/verify")
def verify(token: str):
    users = load_users()
    found = None
    for email, info in users.items():
        if info.get("token") == token:
            found = (email, info)
            break
    if not found:
        raise HTTPException(status_code=400, detail="Invalid token.")
    email, info = found
    expiry = datetime.fromisoformat(info["token_expiry"])
    if datetime.utcnow() > expiry:
        raise HTTPException(status_code=400, detail="Token expired.")
    # mark verified
    users[email]["verified"] = True
    users[email]["token"] = ""  # invalidate
    save_users(users)
    return {"email": email, "verified": True}

# === Health check ===
@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}

# === Run ===
if __name__ == "__main__":
    uvicorn.run("feed_service:app", host="0.0.0.0", port=8000, reload=True)
