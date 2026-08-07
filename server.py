"""
Roblox AI Coder - Full Server (Vostud AI Integration)
Proxies requests to https://vostud-ai.onrender.com
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
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
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

# VOSTUD AI CONFIG
VOSTUD_AI_URL = "https://vostud-ai.onrender.com"
VOSTUD_AI_API_KEY = os.getenv("VOSTUD_AI_API_KEY")

# ==================== FASTAPI SETUP ====================
app = FastAPI(title="Roblox AI Coder", version="5.0.0")

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
pending_codes = {}
user_code_map = {}
CODE_EXPIRY_SECONDS = 600

def generate_pairing_code():
    return str(random.randint(100000, 999999))

# ==================== MODEL QUOTA & LOCKING SYSTEM ====================
model_locks = {}

def lock_model(model_id):
    model_locks[model_id] = {"locked": True, "unlock_time": time.time() + 600}
    logger.warning(f"🔒 Locked model {model_id} due to failure. Retrying in 10 minutes.")

def unlock_model(model_id):
    if model_id in model_locks:
        del model_locks[model_id]
        logger.info(f"🔓 Unlocked model {model_id}")

def is_model_locked(model_id):
    if model_id not in model_locks:
        return False
    if time.time() > model_locks[model_id]["unlock_time"]:
        unlock_model(model_id)
        return False
    return True

# ==================== VOSTUD AI MODEL MAPPING ====================
# Mapping your local model IDs to Vostud AI's endpoint models
VOSTUD_MODEL_MAP = {
    # Vostud Branded Models
    "vostud-2.5-pro": "vostud-2.5-pro",
    "vostud-2.5-flash": "vostud-2.5-flash",
    "vostud-2.0-pro": "vostud-2.0-pro",
    "vostud-2.0-flash": "vostud-2.0-flash",
    "vostud-1.5-pro": "vostud-1.5-pro",
    "vostud-1.5-flash": "vostud-1.5-flash",
    "vostud-pro": "vostud-pro",
    "vostud-flash": "vostud-flash",
    "vostud-local": "vostud-local",
    
    # Existing Local Models mapped to API IDs
    "groq-llama": "groq/llama-3.3-70b-versatile",
    "groq-mixtral": "groq/mixtral-8x7b-32768",
    "deepseek-v3": "deepseek/deepseek-chat",
    "deepseek-r1": "deepseek/deepseek-r1",
    "gemini-2.0-flash": "gemini/gemini-2.0-flash",
    "gemini-2.5-pro": "gemini/gemini-2.5-pro",
    "qwen-2.5-coder": "qwen/qwen-2.5-coder-7b",
    "qwen-2.5-coder-32b": "qwen/qwen-2.5-coder-32b",
    "mistral-7b-instruct": "mistral/mistral-7b-instruct",
    "mistral-small-3.1": "mistral/mistral-small-3.1",
    "gpt-4o": "openai/gpt-4o",
    "claude-3.5-sonnet": "anthropic/claude-3.5-sonnet",
    "claude-3.7-sonnet": "anthropic/claude-3.7-sonnet",
    "nous-hermes": "nousresearch/hermes-2-pro",
    "llama-3.1-8b": "meta-llama/llama-3.1-8b"
}

# Branded models list for the UI
BRANDED_MODELS = {
    "vostud-2.5-pro": {"name": "Vostud 2.5 Pro", "provider": "Vostud AI", "image": "/images/models/vostud.png", "context": "128K tokens", "speed": 7, "intelligence": 10, "cost": 1, "description": "Complex reasoning, research, and advanced coding."},
    "vostud-2.5-flash": {"name": "Vostud 2.5 Flash", "provider": "Vostud AI", "image": "/images/models/vostud.png", "context": "64K tokens", "speed": 10, "intelligence": 8, "cost": 1, "description": "Quick answers, rapid code generation."},
    "vostud-2.0-pro": {"name": "Vostud 2.0 Pro", "provider": "Vostud AI", "image": "/images/models/vostud.png", "context": "128K tokens", "speed": 6, "intelligence": 8, "cost": 1, "description": "Research and general analysis."},
    "vostud-2.0-flash": {"name": "Vostud 2.0 Flash", "provider": "Vostud AI", "image": "/images/models/vostud.png", "context": "32K tokens", "speed": 9, "intelligence": 6, "cost": 1, "description": "General questions and quick tasks."},
    "vostud-1.5-pro": {"name": "Vostud 1.5 Pro", "provider": "Vostud AI", "image": "/images/models/vostud.png", "context": "64K tokens", "speed": 5, "intelligence": 7, "cost": 1, "description": "Quality responses, balanced performance."},
    "vostud-1.5-flash": {"name": "Vostud 1.5 Flash", "provider": "Vostud AI", "image": "/images/models/vostud.png", "context": "16K tokens", "speed": 8, "intelligence": 5, "cost": 1, "description": "Speed optimized, simple tasks."},
    "vostud-pro": {"name": "Vostud Pro", "provider": "Vostud AI", "image": "/images/models/vostud.png", "context": "128K tokens", "speed": 6, "intelligence": 10, "cost": 2, "description": "Best quality. GPT-4 class."},
    "vostud-flash": {"name": "Vostud Flash", "provider": "Vostud AI", "image": "/images/models/vostud.png", "context": "32K tokens", "speed": 8, "intelligence": 6, "cost": 1, "description": "Fast responses. GPT-3.5 class."},
    "vostud-local": {"name": "Vostud Local", "provider": "Vostud AI", "image": "/images/models/vostud.png", "context": "8K tokens", "speed": 4, "intelligence": 7, "cost": 0, "description": "Privacy first, runs offline (requires Ollama)."},
}

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
    if not user: raise HTTPException(status_code=401, detail="Not authenticated")
    user_id = user['id']
    if user_id in user_code_map:
        old_code = user_code_map[user_id]
        code_data = pending_codes.get(old_code)
        if code_data and time.time() < code_data["expires_at"]:
            return {"code": old_code, "expires_in": int(code_data["expires_at"] - time.time()), "new": False}
    code = generate_pairing_code()
    pending_codes[code] = {"user_id": user_id, "email": user['email'], "name": user['name'], "created_at": time.time(), "expires_at": time.time() + CODE_EXPIRY_SECONDS, "pairing_id": None, "roblox_username": None}
    user_code_map[user_id] = code
    logger.info(f"Generated new pairing code {code} for {user['email']}")
    return {"code": code, "expires_in": CODE_EXPIRY_SECONDS, "new": True}

@app.post("/api/validate-code")
async def validate_code(request: Request):
    try:
        data = await request.json()
        code = data.get("code")
        roblox_username = data.get("roblox_username", "UnknownRobloxUser")
        if not code: return {"valid": False, "error": "Code required"}
        code_data = pending_codes.get(code)
        if not code_data or time.time() > code_data["expires_at"]:
            if code_data: pending_codes.pop(code, None); user_code_map.pop(code_data["user_id"], None)
            return {"valid": False, "error": "Invalid or expired code"}
        pairing_id = str(uuid.uuid4())
        code_data["pairing_id"] = pairing_id
        code_data["roblox_username"] = roblox_username
        return {"valid": True, "pairing_id": pairing_id}
    except Exception as e:
        return {"valid": False, "error": str(e)}

@app.post("/api/check-pair")
async def check_pair(request: Request):
    data = await request.json()
    pairing_id = data.get("pairing_id")
    for code, code_data in list(pending_codes.items()):
        if code_data.get("pairing_id") == pairing_id:
            return {"paired": True, "roblox_username": code_data.get("roblox_username", "RobloxUser")}
    return {"paired": False}

@app.post("/api/consume-code")
async def consume_code(request: Request):
    data = await request.json()
    code = data.get("code")
    if not code: return {"success": False, "reason": "Code required"}
    code_data = pending_codes.get(code)
    if not code_data: return {"success": False, "reason": "Already used or expired"}
    pending_codes.pop(code, None); user_code_map.pop(code_data["user_id"], None)
    return {"success": True, "message": "Code consumed successfully"}

@app.post("/api/dashboard-pair-success")
async def dashboard_pair_success(request: Request):
    data = await request.json()
    pairing_id = data.get("pairing_id")
    if pairing_id: logger.info(f"Received pairing success signal for ID: {pairing_id}")
    return {"success": True}

# ==================== PAGE ROUTES ====================
@app.get("/", response_class=RedirectResponse)
async def root(): return RedirectResponse(url="/home")
@app.get("/home", response_class=HTMLResponse)
async def serve_home():
    with open(os.path.join("web", "home.html"), "r", encoding="utf-8") as f: return HTMLResponse(content=f.read())
@app.get("/signup", response_class=HTMLResponse)
async def serve_signup(request: Request):
    if request.session.get('user'): return RedirectResponse(url="/dashboard")
    with open(os.path.join("web", "signup.html"), "r", encoding="utf-8") as f: return HTMLResponse(content=f.read())
@app.get("/dashboard", response_class=HTMLResponse)
async def serve_dashboard(request: Request):
    with open(os.path.join("web", "dashboard.html"), "r", encoding="utf-8") as f: return HTMLResponse(content=f.read())
@app.get("/session")
async def get_session(request: Request):
    user = request.session.get('user')
    if user: return {"logged_in": True, **user}
    return {"logged_in": False}

@app.get("/models")
async def get_models():
    # Combine Branded Models + Regular Models with lock status
    models_with_lock = {}
    for key, val in BRANDED_MODELS.items():
        models_with_lock[key] = {**val, "locked": is_model_locked(key)}
    for key, val in MODELS.items():
        models_with_lock[key] = {**val, "locked": is_model_locked(key)}
    return {"models": models_with_lock}

@app.get("/status")
async def get_status(request: Request):
    user = request.session.get('user')
    if not user: return {"paired": False}
    return {"paired": user['id'] in user_code_map}

# ==================== VOSTUD AI PROXY ENDPOINTS ====================

async def proxy_to_vostud(endpoint: str, payload: dict):
    """Proxies a request to Vostud AI with error handling"""
    if not VOSTUD_AI_API_KEY:
        raise HTTPException(status_code=500, detail="Vostud AI API key is not configured.")
    
    try:
        response = requests.post(
            f"{VOSTUD_AI_URL}/{endpoint}",
            headers={
                "X-API-Key": VOSTUD_AI_API_KEY,
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=60
        )
        
        if response.status_code != 200:
            raise Exception(f"Vostud AI Error (Status {response.status_code}): {response.text}")
        
        return response.json()
    except Exception as e:
        logger.error(f"Vostud AI proxy error: {str(e)}")
        raise HTTPException(status_code=502, detail=f"Vostud AI proxy error: {str(e)}")

@app.post("/api/chat")
async def vostud_chat(request: Request):
    """Proxy to /chat endpoint of Vostud AI"""
    data = await request.json()
    message = data.get("message")
    model = data.get("model", "auto")
    history = data.get("history", [])
    use_rag = data.get("use_rag", True)
    format_type = data.get("format", "detailed")
    
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")
    
    # Translate model if it's a Vostud branded model
    api_model = VOSTUD_MODEL_MAP.get(model, model)
    
    payload = {
        "message": message,
        "history": history,
        "use_rag": use_rag,
        "model": api_model,
        "format": format_type
    }
    
    result = await proxy_to_vostud("chat", payload)
    return JSONResponse(content=result)

@app.post("/api/chat/public")
async def vostud_public_chat(request: Request):
    """Public chat endpoint (no auth)"""
    data = await request.json()
    message = data.get("message")
    model = data.get("model", "auto")
    
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")
    
    payload = {"message": message, "model": model}
    
    try:
        response = requests.post(
            f"{VOSTUD_AI_URL}/chat/public",
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=60
        )
        if response.status_code != 200:
            raise Exception(f"Vostud AI Error: {response.text}")
        return JSONResponse(content=response.json())
    except Exception as e:
        logger.error(f"Public Vostud AI error: {str(e)}")
        raise HTTPException(status_code=502, detail=str(e))

@app.post("/api/upload")
async def vostud_upload(request: Request):
    """Proxy to /upload endpoint"""
    # This expects a multipart/form-data file
    form = await request.form()
    file = form.get("file")
    
    if not file:
        raise HTTPException(status_code=400, detail="No file uploaded")
    
    try:
        files = {"file": (file.filename, await file.read(), file.content_type)}
        response = requests.post(
            f"{VOSTUD_AI_URL}/upload",
            headers={"X-API-Key": VOSTUD_AI_API_KEY},
            files=files
        )
        if response.status_code != 200:
            raise Exception(f"Upload failed: {response.text}")
        return JSONResponse(content=response.json())
    except Exception as e:
        logger.error(f"Upload proxy error: {str(e)}")
        raise HTTPException(status_code=502, detail=str(e))

@app.post("/api/quiz")
async def vostud_quiz(request: Request):
    """Proxy to /quiz endpoint"""
    data = await request.json()
    topic = data.get("topic")
    num_questions = data.get("num_questions", 5)
    
    if not topic:
        raise HTTPException(status_code=400, detail="Topic is required")
    
    payload = {"topic": topic, "num_questions": num_questions}
    result = await proxy_to_vostud("quiz", payload)
    return JSONResponse(content=result)

@app.get("/api/keys")
async def vostud_list_keys():
    """List API keys"""
    return await proxy_to_vostud("keys", {})

@app.post("/api/keys/generate")
async def vostud_generate_key(request: Request):
    """Generate a new API key"""
    data = await request.json()
    name = data.get("name", "Generated Key")
    expires_in_days = data.get("expires_in_days", 365)
    payload = {"name": name, "expires_in_days": expires_in_days}
    return await proxy_to_vostud("keys/generate", payload)

@app.delete("/api/keys/{prefix}")
async def vostud_revoke_key(prefix: str):
    """Revoke an API key"""
    return await proxy_to_vostud(f"keys/{prefix}", {})

@app.get("/api/usage")
async def vostud_usage():
    """Get usage statistics"""
    return await proxy_to_vostud("usage", {})

@app.get("/api/usage/check")
async def vostud_check_limits():
    """Check current rate limits"""
    return await proxy_to_vostud("usage/check", {})

@app.get("/api/vostud-models")
async def vostud_models():
    """List available models from Vostud AI"""
    try:
        response = requests.get(
            f"{VOSTUD_AI_URL}/models",
            headers={"X-API-Key": VOSTUD_AI_API_KEY}
        )
        if response.status_code != 200:
            raise Exception(f"Failed to fetch models: {response.text}")
        return JSONResponse(content=response.json())
    except Exception as e:
        logger.error(f"Failed to fetch models: {str(e)}")
        raise HTTPException(status_code=502, detail=str(e))

@app.post("/api/models/switch")
async def vostud_switch_model(request: Request):
    """Switch the active model"""
    data = await request.json()
    model = data.get("model")
    if not model:
        raise HTTPException(status_code=400, detail="Model is required")
    return await proxy_to_vostud("models/switch", {"model": model})

@app.post("/api/support/ticket")
async def vostud_create_ticket(request: Request):
    """Create a support ticket"""
    data = await request.json()
    subject = data.get("subject")
    message = data.get("message")
    category = data.get("category", "technical")
    
    if not subject or not message:
        raise HTTPException(status_code=400, detail="Subject and message are required")
    
    return await proxy_to_vostud("support/ticket", {
        "subject": subject,
        "message": message,
        "category": category
    })

@app.post("/api/support/public-appeal")
async def vostud_public_appeal(request: Request):
    """Submit a public appeal (no auth)"""
    data = await request.json()
    email = data.get("email")
    message = data.get("message")
    
    if not email or not message:
        raise HTTPException(status_code=400, detail="Email and message are required")
    
    try:
        response = requests.post(
            f"{VOSTUD_AI_URL}/support/public-appeal",
            headers={"Content-Type": "application/json"},
            json={"email": email, "message": message}
        )
        if response.status_code != 200:
            raise Exception(f"Appeal failed: {response.text}")
        return JSONResponse(content=response.json())
    except Exception as e:
        logger.error(f"Public appeal error: {str(e)}")
        raise HTTPException(status_code=502, detail=str(e))

@app.get("/api/support/appeal")
async def vostud_check_appeal():
    """Check appeal status"""
    return await proxy_to_vostud("support/appeal", {})

@app.get("/api/health")
async def vostud_health_check():
    """Check Vostud AI health"""
    try:
        response = requests.get(f"{VOSTUD_AI_URL}/health", timeout=10)
        if response.status_code == 200:
            return {"status": "healthy", "vostud_ai": response.json()}
        return {"status": "degraded", "vostud_ai": {"status": "unhealthy"}}
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return {"status": "unhealthy", "error": str(e)}

# ==================== OAUTH ====================
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

@app.get('/auth/roblox')
async def login_roblox(request: Request):
    redirect_uri = str(request.base_url) + "auth/roblox/callback"
    auth_url = f"https://apis.roblox.com/oauth/v1/authorize?client_id={ROBLOX_CLIENT_ID}&redirect_uri={redirect_uri}&response_type=code&scope=openid%20profile"
    return RedirectResponse(url=auth_url)

@app.get('/auth/roblox/callback')
async def roblox_callback(request: Request):
    code = request.query_params.get('code')
    token_url = "https://apis.roblox.com/oauth/v1/token"
    redirect_uri = str(request.base_url) + "auth/roblox/callback"
    payload = {"client_id": ROBLOX_CLIENT_ID, "client_secret": ROBLOX_CLIENT_SECRET, "code": code, "grant_type": "authorization_code", "redirect_uri": redirect_uri}
    resp = requests.post(token_url, data=payload)
    token_data = resp.json()
    headers = {"Authorization": f"Bearer {token_data['access_token']}"}
    user_resp = requests.get("https://apis.roblox.com/oauth/v1/userinfo", headers=headers)
    user_info = user_resp.json()
    request.session['user'] = {'id': user_info['sub'], 'name': user_info['name'], 'email': user_info.get('email', 'No Email Provided'), 'picture': None, 'provider': 'roblox'}
    return RedirectResponse(url="/dashboard")

@app.get('/auth/logout')
async def logout(request: Request):
    request.session.pop('user', None)
    return RedirectResponse(url="/home")

# ==================== EXISTING AI GENERATION (FALLBACK) ====================
MODELS = {
    "groq-llama": {"name": "Llama 3.3 70B", "provider": "Groq / Meta", "api": "groq", "id": "llama-3.3-70b-versatile", "image": "/images/models/meta.png", "context": "128K tokens", "speed": 10, "intelligence": 9, "cost": 1, "images": False, "cost_per_request": "Free", "description": "Ultra-fast coding model via Groq's free tier."},
    "groq-mixtral": {"name": "Mixtral 8x7B", "provider": "Groq / Mistral", "api": "groq", "id": "mixtral-8x7b-32768", "image": "/images/models/grok.png", "context": "32K tokens", "speed": 8, "intelligence": 7, "cost": 1, "images": False, "cost_per_request": "Free", "description": "Excellent legacy model."},
    "deepseek-v3": {"name": "DeepSeek V3", "provider": "DeepSeek", "api": "openrouter", "id": "deepseek/deepseek-chat", "image": "/images/models/deepseek.png", "context": "64K tokens", "speed": 9, "intelligence": 10, "cost": 1, "images": False, "cost_per_request": "Free", "description": "Open-source powerhouse."},
    "deepseek-r1": {"name": "DeepSeek R1", "provider": "DeepSeek", "api": "openrouter", "id": "deepseek/deepseek-r1", "image": "/images/models/deepseek.png", "context": "128K tokens", "speed": 7, "intelligence": 10, "cost": 1, "images": False, "cost_per_request": "Free", "description": "Reasoning powerhouse for complex logic."},
    "gemini-2.0-flash": {"name": "Gemini 2.0 Flash", "provider": "Google", "api": "openrouter", "id": "google/gemini-2.0-flash-exp", "image": "/images/models/google.png", "context": "1M tokens", "speed": 10, "intelligence": 7, "cost": 1, "images": True, "cost_per_request": "Free", "description": "Sub-second latency."},
    "gemini-2.5-pro": {"name": "Gemini 2.5 Pro", "provider": "Google", "api": "openrouter", "id": "google/gemini-2.5-pro-exp-03-25", "image": "/images/models/google.png", "context": "2M tokens", "speed": 7, "intelligence": 10, "cost": 1, "images": True, "cost_per_request": "Free", "description": "Massive context window for large scripts."},
    "qwen-2.5-coder": {"name": "Qwen 2.5 Coder 7B", "provider": "Alibaba", "api": "openrouter", "id": "qwen/qwen-2.5-coder-7b-instruct", "image": "/images/models/alibaba.png", "context": "32K tokens", "speed": 8, "intelligence": 6, "cost": 1, "images": False, "cost_per_request": "Free", "description": "Tiny and lightning fast."},
    "qwen-2.5-coder-32b": {"name": "Qwen 2.5 Coder 32B", "provider": "Alibaba", "api": "openrouter", "id": "qwen/qwen-2.5-coder-32b-instruct", "image": "/images/models/alibaba.png", "context": "32K tokens", "speed": 6, "intelligence": 9, "cost": 1, "images": False, "cost_per_request": "Free", "description": "Powerful local-like coder."},
    "mistral-7b-instruct": {"name": "Mistral 7B", "provider": "Mistral", "api": "openrouter", "id": "mistralai/mistral-7b-instruct", "image": "/images/models/mistral.png", "context": "8K tokens", "speed": 7, "intelligence": 5, "cost": 1, "images": False, "cost_per_request": "Free", "description": "Lightweight and fast."},
    "mistral-small-3.1": {"name": "Mistral Small 3.1", "provider": "Mistral", "api": "openrouter", "id": "mistralai/mistral-small-3.1-24b-instruct-2505", "image": "/images/models/mistral.png", "context": "32K tokens", "speed": 7, "intelligence": 8, "cost": 1, "images": False, "cost_per_request": "Free", "description": "Excellent small model for utilities."},
    "gpt-4o": {"name": "GPT-4o", "provider": "OpenAI", "api": "openrouter", "id": "openai/gpt-4o", "image": "/images/models/openai.png", "context": "128K tokens", "speed": 8, "intelligence": 10, "cost": 8, "images": True, "cost_per_request": "$0.03", "description": "The gold standard for coding."},
    "claude-3.5-sonnet": {"name": "Claude 3.5 Sonnet", "provider": "Anthropic", "api": "openrouter", "id": "anthropic/claude-3.5-sonnet", "image": "/images/models/anthropic.png", "context": "200K tokens", "speed": 7, "intelligence": 10, "cost": 6, "images": True, "cost_per_request": "$0.03", "description": "Incredible formatting."},
    "claude-3.7-sonnet": {"name": "Claude 3.7 Sonnet", "provider": "Anthropic", "api": "openrouter", "id": "anthropic/claude-3.7-sonnet", "image": "/images/models/anthropic.png", "context": "200K tokens", "speed": 8, "intelligence": 10, "cost": 6, "images": True, "cost_per_request": "$0.03", "description": "Latest Anthropic model with reasoning."},
    "nous-hermes": {"name": "Nous Hermes 2 Pro", "provider": "Nous Research", "api": "openrouter", "id": "nousresearch/hermes-2-pro-mistral-7b", "image": "/images/models/default.png", "context": "32K tokens", "speed": 7, "intelligence": 7, "cost": 1, "images": False, "cost_per_request": "Free", "description": "Great for general bot logic."},
    "llama-3.1-8b": {"name": "Llama 3.1 8B", "provider": "Meta", "api": "openrouter", "id": "meta-llama/llama-3.1-8b-instruct", "image": "/images/models/meta.png", "context": "128K tokens", "speed": 10, "intelligence": 7, "cost": 1, "images": False, "cost_per_request": "Free", "description": "Ultra-lightweight and fast."},
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

def generate_with_openrouter(model_id, prompt):
    if not OPENROUTER_API_KEY: raise Exception("OPENROUTER_API_KEY missing.")
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": model_id, "messages": [{"role": "system", "content": "You are a Roblox Lua expert. Output ONLY Lua code."}, {"role": "user", "content": prompt}], "temperature": 0.2, "max_tokens": 3000, "transforms": ["middle-out"]}
    response = requests.post("https://openrouter.ai/api/v1/chat/completions", json=payload, headers=headers, timeout=60)
    if response.status_code != 200:
        if response.status_code == 404 or response.status_code == 429:
            raise Exception(f"OpenRouter Error: Model Unavailable (Code {response.status_code})")
        raise Exception(f"OpenRouter Error: {response.text}")
    return clean_code(response.json()["choices"][0]["message"]["content"])

@app.post("/generate", response_model=GenerateResponse)
async def generate_code(request: GenerateRequest):
    if not request.prompt: raise HTTPException(status_code=400, detail="No prompt provided")
    
    original_model_id = request.model_id
    model_id = original_model_id
    
    if model_id == "auto" or model_id not in MODELS or is_model_locked(model_id):
        model_id = "groq-llama"
    
    model_config = MODELS.get(model_id)
    if not model_config:
        model_id = "groq-llama"
        model_config = MODELS.get(model_id)
        if not model_config: raise HTTPException(status_code=500, detail="Critical error: No available models.")

    try:
        if model_config["api"] == "groq":
            code = generate_with_groq(model_config["id"], request.prompt)
        else:
            code = generate_with_openrouter(model_config["id"], request.prompt)
        
        unlock_model(model_id)
        
        code_id = str(uuid.uuid4())
        code_queue.append({"id": code_id, "code": code, "scriptName": request.prompt[:30].replace(" ", "_"), "destination": request.destination, "timestamp": time.time()})
        if len(code_queue) > MAX_QUEUE_SIZE: code_queue.popleft()
        return GenerateResponse(code=code, queued=True, id=code_id, model_used=model_config["name"])
        
    except Exception as e:
        logger.error(f"Generation failed for {model_id}: {str(e)}")
        if "ConnectionError" not in str(e) and "Timeout" not in str(e):
            lock_model(model_id)
        
        try:
            logger.info(f"Attempting emergency fallback to Groq Llama...")
            fallback_code = generate_with_groq("llama-3.3-70b-versatile", request.prompt)
            fallback_id = str(uuid.uuid4())
            code_queue.append({"id": fallback_id, "code": fallback_code, "scriptName": request.prompt[:30].replace(" ", "_") + "_Fallback", "destination": request.destination, "timestamp": time.time()})
            if len(code_queue) > MAX_QUEUE_SIZE: code_queue.popleft()
            return GenerateResponse(code=fallback_code, queued=True, id=fallback_id, model_used="Llama 3.3 70B (Fallback)")
        except Exception as fallback_e:
            logger.error(f"Emergency fallback also failed: {str(fallback_e)}")
            raise HTTPException(status_code=500, detail="All AI models are currently unavailable. Check API keys or quotas.")

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
    logger.info("=" * 50)
    logger.info("🚀 Roblox AI Coder v5.0.0 - Vostud AI Integration")
    logger.info("🌐 Server running on port 8000")
    logger.info("=" * 50)
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
