from fastapi import FastAPI, Request, Form, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uuid, json, os, smtplib
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()
origins = ["*"]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])

OPP_FILE = "opportunities_store.json"
USER_FILE = "users_store.json"

EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))

class Opportunity(BaseModel):
    id: str
    title: str
    description: str
    location: str
    type: str
    category: str
    deadline: str
    apply_link: str
    posted_by: str

def load_json(file):
    if not os.path.exists(file): return []
    with open(file) as f:
        return json.load(f)

def save_json(data, file):
    with open(file, "w") as f:
        json.dump(data, f, indent=2)

@app.get("/")
def root():
    return {"status": "running"}

@app.get("/opportunities")
def get_opportunities():
    return load_json(OPP_FILE)

@app.post("/opportunities")
def post_opportunity(opp: Opportunity):
    data = load_json(OPP_FILE)
    data.append(opp.dict())
    save_json(data, OPP_FILE)
    return {"status": "success", "total": len(data)}

@app.delete("/opportunities/{id}")
def delete_opp(id: str):
    data = load_json(OPP_FILE)
    data = [x for x in data if x["id"] != id]
    save_json(data, OPP_FILE)
    return {"status": "deleted"}

@app.post("/signup")
def signup(email: str = Form(...)):
    users = load_json(USER_FILE)
    token = str(uuid.uuid4())
    users.append({"email": email, "token": token, "verified": False})
    save_json(users, USER_FILE)
    
    # Send email
    msg = MIMEText(f"Click to verify: https://yourfrontend.com/verify.html?token={token}")
    msg["Subject"] = "Verify Your Email"
    msg["From"] = EMAIL_FROM
    msg["To"] = email

    try:
        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
            server.starttls()
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.sendmail(EMAIL_FROM, email, msg.as_string())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "sent"}

@app.get("/verify")
def verify_user(token: str = Query(...)):
    users = load_json(USER_FILE)
    for user in users:
        if user["token"] == token:
            user["verified"] = True
            save_json(users, USER_FILE)
            return HTMLResponse("<h1>Verified! You can now post opportunities.</h1>")
    return HTMLResponse("<h1>Invalid token</h1>")
