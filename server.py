"""
Roblox AI Coder - Pairing Code System
Handles Code Generation, Validation, and User Linking
"""

import os
import re
import uuid
import time
import logging
import secrets
import random
import requests
import uvicorn
from collections import deque, defaultdict
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== CONFIGURATION ====================
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
ROBLOX_CLIENT_ID = os.getenv("ROBLOX_CLIENT_ID")
ROBLOX_CLIENT_SECRET = os.getenv("ROBLOX_CLIENT_SECRET")
SESSION_SECRET = os.getenv("SESSION_SECRET")
if not SESSION_SECRET:
    SESSION_SECRET = secrets.token_urlsafe(32)

# ==================== FASTAPI SETUP ====================
app = FastAPI(title="Roblox AI Coder", version="4.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)
app.mount("/static", StaticFiles(directory="web"), name="static")
app.mount("/images", StaticFiles(directory="web/images"), name="images")

# ==================== CODE PAIRING SYSTEM ====================
# Stores: code -> { user_id, email, name, expires_at }
pending_codes = {}
# Stores: user_id -> code (for quick lookup)
user_code_map = {}

CODE_EXPIRY_SECONDS = 600  # 10 minutes

def generate_pairing_code():
    return str(random.randint(100000, 999999)) # 6-digit code

@app.post("/api/generate-code")
async def generate_code(request: Request):
    user = request.session.get('user')
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Remove old code if they already have one
    user_id = user['id']
    if user_id in user_code_map:
        old_code = user_code_map[user_id]
        pending_codes.pop(old_code, None)
        user_code_map.pop(user_id, None)
    
    # Create new code
    code = generate_pairing_code()
    pending_codes[code] = {
        "user_id": user_id,
        "email": user['email'],
        "name": user['name'],
        "created_at": time.time(),
        "expires_at": time.time() + CODE_EXPIRY_SECONDS
    }
    user_code_map[user_id] = code
    
    return {"code": code, "expires_in": CODE_EXPIRY_SECONDS}

@app.post("/api/validate-code")
async def validate_code(request: Request):
    data = await request.json()
    code = data.get("code")
    
    if not code:
        raise HTTPException(status_code=400, detail="Code required")
    
    code_data = pending_codes.get(code)
    if not code_data:
        raise HTTPException(status_code=404, detail="Invalid or expired code")
    
    if time.time() > code_data["expires_at"]:
        pending_codes.pop(code, None)
        user_code_map.pop(code_data["user_id"], None)
        raise HTTPException(status_code=410, detail="Code has expired")
    
    # Valid code! Return user info to the plugin
    # IMPORTANT: Do NOT delete the code yet. The plugin will send a /api/consume-code request later.
    return {
        "valid": True,
        "email": code_data["email"],
        "name": code_data["name"]
    }

@app.post("/api/consume-code")
async def consume_code(request: Request):
    """Called by the plugin after successfully linking to consume the code"""
    data = await request.json()
    code = data.get("code")
    
    if not code:
        raise HTTPException(status_code=400, detail="Code required")
    
    code_data = pending_codes.get(code)
    if not code_data:
        return {"success": False, "reason": "Already used or expired"}
    
    # Consume it (Delete it permanently)
    pending_codes.pop(code, None)
    user_code_map.pop(code_data["user_id"], None)
    
    return {"success": True, "message": "Code consumed successfully"}

# ==================== PAGE ROUTES ====================
@app.get("/", response_class=RedirectResponse)
async def root(): return RedirectResponse(url="/home")

@app.get("/home", response_class=HTMLResponse)
async def serve_home():
    with open(os.path.join("web", "home.html"), "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.get("/signup", response_class=HTMLResponse)
async def serve_signup(request: Request):
    if request.session.get('user'): return RedirectResponse(url="/dashboard")
    with open(os.path.join("web", "signup.html"), "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.get("/dashboard", response_class=HTMLResponse)
async def serve_dashboard(request: Request):
    with open(os.path.join("web", "dashboard.html"), "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.get("/session")
async def get_session(request: Request):
    user = request.session.get('user')
    if user: return {"logged_in": True, **user}
    return {"logged_in": False}

# ==================== OAUTH ROUTES (GOOGLE & ROBLOX) ====================
@app.get('/auth/google')
async def login_google(request: Request):
    redirect_uri = str(request.base_url) + "auth/google/callback"
    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={GOOGLE_CLIENT_ID}&redirect_uri={redirect_uri}&"
        "response_type=code&scope=openid%20email%20profile&prompt=select_account"
    )
    return RedirectResponse(url=auth_url)

@app.get('/auth/google/callback')
async def google_callback(request: Request):
    code = request.query_params.get('code')
    token_url = "https://oauth2.googleapis.com/token"
    redirect_uri = str(request.base_url) + "auth/google/callback"
    payload = {
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri
    }
    resp = requests.post(token_url, data=payload)
    token_data = resp.json()
    headers = {"Authorization": f"Bearer {token_data['access_token']}"}
    user_resp = requests.get("https://www.googleapis.com/oauth2/v1/userinfo", headers=headers)
    user_info = user_resp.json()
    request.session['user'] = {
        'id': user_info['id'],
        'name': user_info['name'],
        'email': user_info['email'],
        'picture': user_info.get('picture'),
        'provider': 'google'
    }
    return RedirectResponse(url="/dashboard")

@app.get('/auth/roblox')
async def login_roblox(request: Request):
    redirect_uri = str(request.base_url) + "auth/roblox/callback"
    auth_url = (
        "https://apis.roblox.com/oauth/v1/authorize?"
        f"client_id={ROBLOX_CLIENT_ID}&redirect_uri={redirect_uri}&"
        "response_type=code&scope=openid%20profile"
    )
    return RedirectResponse(url=auth_url)

@app.get('/auth/roblox/callback')
async def roblox_callback(request: Request):
    code = request.query_params.get('code')
    token_url = "https://apis.roblox.com/oauth/v1/token"
    redirect_uri = str(request.base_url) + "auth/roblox/callback"
    payload = {
        "client_id": ROBLOX_CLIENT_ID,
        "client_secret": ROBLOX_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri
    }
    resp = requests.post(token_url, data=payload)
    token_data = resp.json()
    headers = {"Authorization": f"Bearer {token_data['access_token']}"}
    user_resp = requests.get("https://apis.roblox.com/oauth/v1/userinfo", headers=headers)
    user_info = user_resp.json()
    request.session['user'] = {
        'id': user_info['sub'],
        'name': user_info['name'],
        'email': user_info.get('email', 'No Email Provided'),
        'picture': None,
        'provider': 'roblox'
    }
    return RedirectResponse(url="/dashboard")

@app.get('/auth/logout')
async def logout(request: Request):
    request.session.pop('user', None)
    return RedirectResponse(url="/home")

# ==================== AI MODELS & GENERATION ====================
MODELS = {
    "groq-llama": {"name": "Llama 3.3 70B", "provider": "Groq / Meta", "api": "groq", "id": "llama-3.3-70b-versatile", "image": "/images/models/meta.png", "context": "128K tokens", "speed": 10, "intelligence": 9, "cost": 1, "images": False, "cost_per_request": "Free", "description": "Ultra-fast coding model via Groq's free tier."},
    "deepseek-v3": {"name": "DeepSeek V3", "provider": "DeepSeek", "api": "openrouter", "id": "deepseek/deepseek-chat", "image": "/images/models/deepseek.png", "context": "64K tokens", "speed": 9, "intelligence": 10, "cost": 1, "images": False, "cost_per_request": "Free", "description": "Open-source powerhouse."},
}

code_queue = deque()
MAX_QUEUE_SIZE = 100

class GenerateRequest(BaseModel):
    prompt: str
    model_id: str = "groq-llama"
    destination: str = "ServerScriptService"

class GenerateResponse(BaseModel):
    code: str
    queued: bool
    id: str
    model_used: str

def generate_with_groq(model_id, prompt):
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": model_id, "messages": [{"role": "system", "content": "You are a Roblox Lua expert. Output ONLY Lua code."}, {"role": "user", "content": prompt}], "temperature": 0.2, "max_tokens": 3000}
    response = requests.post("https://api.groq.com/openai/v1/chat/completions", json=payload, headers=headers, timeout=30)
    return response.json()["choices"][0]["message"]["content"]

@app.post("/generate", response_model=GenerateResponse)
async def generate_code(request: GenerateRequest):
    import re
    def clean_code(code):
        return re.sub(r'```(lua|luau)?\s*', '', code).strip()
    
    prompt = f"You are an expert Roblox Lua developer. Generate ONLY valid Lua code. User request: {request.prompt}\nLua code:"
    if GROQ_API_KEY:
        raw = generate_with_groq("llama-3.3-70b-versatile", prompt)
    else:
        raw = "print('No AI key configured')"
    
    code_id = str(uuid.uuid4())
    code_queue.append({"id": code_id, "code": clean_code(raw), "scriptName": request.prompt[:30].replace(" ", "_"), "destination": request.destination, "timestamp": time.time()})
    if len(code_queue) > MAX_QUEUE_SIZE: code_queue.popleft()
    return GenerateResponse(code=clean_code(raw), queued=True, id=code_id, model_used="Llama 3.3 70B")

@app.get("/queue/next")
async def get_next_code():
    if code_queue:
        item = code_queue[0]
        return {"id": item["id"], "code": item["code"], "scriptName": item["scriptName"], "destination": item["destination"]}
    return {"code": None}

@app.post("/queue/ack")
async def acknowledge_code(request: dict):
    code_id = request.get("id")
    for i, item in enumerate(code_queue):
        if item["id"] == code_id:
            code_queue.remove(item)
            return {"success": True}
    return {"success": False}

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
