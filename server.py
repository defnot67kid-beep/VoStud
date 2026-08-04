"""
Roblox AI Coder - Full Server (One-Code Pairing System)
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
from collections import deque
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
app = FastAPI(title="Roblox AI Coder", version="4.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)
app.mount("/static", StaticFiles(directory="web"), name="static")
app.mount("/images", StaticFiles(directory="web/images"), name="images")

# ==================== GLOBAL STATE ====================
plugin_state = {
    "ServerScriptService": [],
    "ReplicatedStorage": [],
    "StarterGui": [],
    "StarterPlayer": [],
    "Workspace": [],
    "ServerStorage": []
}

# Code Pairing System
pending_codes = {}
user_code_map = {}
CODE_EXPIRY_SECONDS = 600

def generate_pairing_code():
    return str(random.randint(100000, 999999))

# ==================== PLUGIN DATA ENDPOINTS ====================
@app.post("/api/plugin-data")
async def receive_plugin_data(request: Request):
    try:
        data = await request.json()
        global plugin_state
        plugin_state = data
        return {"success": True}
    except Exception as e:
        logger.error(f"Failed to process plugin data: {str(e)}")
        return {"success": False, "error": str(e)}

@app.get("/api/plugin-data")
async def get_plugin_data():
    global plugin_state
    return plugin_state

# ==================== PAIRING ENDPOINTS ====================
@app.post("/api/generate-code")
async def generate_code(request: Request):
    user = request.session.get('user')
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    user_id = user['id']
    
    # BLOCK: Check if they already have a valid, unexpired code
    if user_id in user_code_map:
        old_code = user_code_map[user_id]
        code_data = pending_codes.get(old_code)
        if code_data and time.time() < code_data["expires_at"]:
            # Re-send the existing code
            return {"code": old_code, "expires_in": int(code_data["expires_at"] - time.time()), "new": False}
    
    # Generate new code
    code = generate_pairing_code()
    pending_codes[code] = {
        "user_id": user_id,
        "email": user['email'],
        "name": user['name'],
        "created_at": time.time(),
        "expires_at": time.time() + CODE_EXPIRY_SECONDS,
        "pairing_id": None,
        "roblox_username": None
    }
    user_code_map[user_id] = code
    
    logger.info(f"Generated new pairing code {code} for {user['email']}")
    return {"code": code, "expires_in": CODE_EXPIRY_SECONDS, "new": True}

@app.post("/api/validate-code")
async def validate_code(request: Request):
    try:
        data = await request.json()
        code = data.get("code")
        roblox_username = data.get("roblox_username", "UnknownRobloxUser")
        
        logger.info(f"Received validation request for code: {code} from {roblox_username}")
        
        if not code:
            return {"valid": False, "error": "Code required"}
        
        code_data = pending_codes.get(code)
        if not code_data:
            return {"valid": False, "error": "Invalid or expired code"}
        
        if time.time() > code_data["expires_at"]:
            pending_codes.pop(code, None)
            user_code_map.pop(code_data["user_id"], None)
            return {"valid": False, "error": "Code has expired"}
        
        pairing_id = str(uuid.uuid4())
        code_data["pairing_id"] = pairing_id
        code_data["roblox_username"] = roblox_username

        logger.info(f"Code {code} validated by {roblox_username}")
        
        return {"valid": True, "pairing_id": pairing_id}
    except Exception as e:
        logger.error(f"Validation error: {str(e)}")
        return {"valid": False, "error": str(e)}

@app.post("/api/check-pair")
async def check_pair(request: Request):
    data = await request.json()
    pairing_id = data.get("pairing_id")
    
    if not pairing_id:
        return {"paired": False}
    
    for code, code_data in list(pending_codes.items()):
        if code_data.get("pairing_id") == pairing_id:
            return {
                "paired": True, 
                "roblox_username": code_data.get("roblox_username", "RobloxUser")
            }
    
    return {"paired": False}

@app.post("/api/consume-code")
async def consume_code(request: Request):
    data = await request.json()
    code = data.get("code")
    if not code:
        return {"success": False, "reason": "Code required"}
    code_data = pending_codes.get(code)
    if not code_data:
        return {"success": False, "reason": "Already used or expired"}
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

@app.get("/models")
async def get_models():
    return {"models": MODELS}

@app.get("/status")
async def get_status(request: Request):
    user = request.session.get('user')
    if not user:
        return {"paired": False}
    return {"paired": user['id'] in user_code_map}

# ==================== OAUTH & AI ====================
MODELS = {
    "groq-llama": {"name": "Llama 3.3 70B", "provider": "Groq / Meta", "api": "groq", "id": "llama-3.3-70b-versatile", "image": "/images/models/meta.png", "context": "128K tokens", "speed": 10, "intelligence": 9, "cost": 1, "images": False, "cost_per_request": "Free", "description": "Ultra-fast coding model via Groq's free tier."},
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

def clean_code(code: str) -> str:
    if not code: return ""
    code = re.sub(r'```(lua|luau)?\s*', '', code)
    return code.strip()

def generate_with_groq(model_id, prompt):
    if not GROQ_API_KEY: raise Exception("GROQ_API_KEY missing.")
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": model_id, "messages": [{"role": "system", "content": "You are a Roblox Lua expert. Output ONLY Lua code."}, {"role": "user", "content": prompt}], "temperature": 0.2, "max_tokens": 3000}
    response = requests.post("https://api.groq.com/openai/v1/chat/completions", json=payload, headers=headers, timeout=30)
    if response.status_code != 200: raise Exception(f"Groq Error: {response.text}")
    return clean_code(response.json()["choices"][0]["message"]["content"])

@app.post("/generate", response_model=GenerateResponse)
async def generate_code(request: GenerateRequest):
    if not request.prompt: raise HTTPException(status_code=400, detail="No prompt provided")
    model_config = MODELS.get(request.model_id)
    if not model_config: raise HTTPException(status_code=400, detail="Invalid model ID")
    try:
        code = generate_with_groq(model_config["id"], request.prompt)
        code_id = str(uuid.uuid4())
        code_queue.append({"id": code_id, "code": code, "scriptName": request.prompt[:30].replace(" ", "_"), "destination": request.destination, "timestamp": time.time()})
        if len(code_queue) > MAX_QUEUE_SIZE: code_queue.popleft()
        return GenerateResponse(code=code, queued=True, id=code_id, model_used=model_config["name"])
    except Exception as e:
        logger.error(f"Generation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

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

@app.get('/auth/google')
async def login_google(request: Request):
    redirect_uri = str(request.base_url) + "auth/google/callback"
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?client_id={GOOGLE_CLIENT_ID}&redirect_uri={redirect_uri}&response_type=code&scope=openid%20email%20profile&prompt=select_account"
    return RedirectResponse(url=auth_url)

@app.get('/auth/google/callback')
async def google_callback(request: Request):
    code = request.query_params.get('code')
    token_url = "https://oauth2.googleapis.com/token"
    redirect_uri = str(request.base_url) + "auth/google/callback"
    payload = {"client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_CLIENT_SECRET, "code": code, "grant_type": "authorization_code", "redirect_uri": redirect_uri}
    resp = requests.post(token_url, data=payload)
    token_data = resp.json()
    headers = {"Authorization": f"Bearer {token_data['access_token']}"}
    user_resp = requests.get("https://www.googleapis.com/oauth2/v1/userinfo", headers=headers)
    user_info = user_resp.json()
    request.session['user'] = {'id': user_info['id'], 'name': user_info['name'], 'email': user_info['email'], 'picture': user_info.get('picture'), 'provider': 'google'}
    return RedirectResponse(url="/dashboard")

@app.get('/auth/logout')
async def logout(request: Request):
    request.session.pop('user', None)
    return RedirectResponse(url="/home")

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
