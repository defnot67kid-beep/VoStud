"""
Roblox AI Coder - Final Production Server (Supports Model Logos)
Handles Real Google & Roblox Login, Sessions, and AI Generation
"""

import os
import re
import uuid
import time
import logging
import secrets
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

# OAuth Credentials
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
ROBLOX_CLIENT_ID = os.getenv("ROBLOX_CLIENT_ID")
ROBLOX_CLIENT_SECRET = os.getenv("ROBLOX_CLIENT_SECRET")

# Session Security
SESSION_SECRET = os.getenv("SESSION_SECRET")
if not SESSION_SECRET:
    SESSION_SECRET = secrets.token_urlsafe(32)
    logger.warning("⚠️ SESSION_SECRET not found. Generated a random one. Logins will reset on restart.")

# ==================== FASTAPI SETUP ====================
app = FastAPI(title="Roblox AI Coder", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)

# ==================== SERVE STATIC FILES ====================
app.mount("/static", StaticFiles(directory="web"), name="static")
# Mount the images folder so the browser can load model logos
app.mount("/images", StaticFiles(directory="web/images"), name="images")

# ==================== PAGE ROUTES ====================
@app.get("/", response_class=RedirectResponse)
async def root():
    return RedirectResponse(url="/home")

@app.get("/home", response_class=HTMLResponse)
async def serve_home():
    html_path = os.path.join("web", "home.html")
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Home page not found.</h1>")

@app.get("/signup", response_class=HTMLResponse)
async def serve_signup(request: Request):
    user = request.session.get('user')
    if user:
        return RedirectResponse(url="/dashboard")
        
    html_path = os.path.join("web", "signup.html")
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Signup page not found.</h1>")

@app.get("/dashboard", response_class=HTMLResponse)
async def serve_dashboard(request: Request):
    html_path = os.path.join("web", "dashboard.html")
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Dashboard page not found.</h1>")

# ==================== SESSION CHECK ====================
@app.get("/session")
async def get_session(request: Request):
    user = request.session.get('user')
    if user:
        return {
            "logged_in": True,
            "name": user.get('name', 'User'),
            "email": user.get('email', 'No Email'),
            "provider": user.get('provider', 'unknown')
        }
    return {"logged_in": False}

# ==================== GOOGLE OAUTH ====================
@app.get('/auth/google')
async def login_google(request: Request):
    if not GOOGLE_CLIENT_ID:
        return HTMLResponse(content="<h1>Google Login not configured.</h1>")
    
    redirect_uri = str(request.base_url) + "auth/google/callback"
    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={GOOGLE_CLIENT_ID}&"
        f"redirect_uri={redirect_uri}&"
        "response_type=code&"
        "scope=openid%20email%20profile"
    )
    return RedirectResponse(url=auth_url)

@app.get('/auth/google/callback')
async def google_callback(request: Request):
    code = request.query_params.get('code')
    if not code:
        return HTMLResponse(content="<h1>Error: Missing authorization code</h1>")

    try:
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
        if resp.status_code != 200:
            return HTMLResponse(content="<h1>Failed to get Google token.</h1>")
        
        token_data = resp.json()
        access_token = token_data.get("access_token")
        
        headers = {"Authorization": f"Bearer {access_token}"}
        user_resp = requests.get("https://www.googleapis.com/oauth2/v1/userinfo", headers=headers)
        if user_resp.status_code == 200:
            user_info = user_resp.json()
            request.session['user'] = {
                'id': user_info['id'],
                'name': user_info['name'],
                'email': user_info['email'],
                'provider': 'google'
            }
            logger.info(f"User logged in via Google: {user_info['email']}")
            return RedirectResponse(url="/dashboard")

        return HTMLResponse(content="<h1>Failed to get Google user info.</h1>")

    except Exception as e:
        logger.error(f"Google Callback Error: {str(e)}")
        return HTMLResponse(content=f"<h1>Authentication Error: {str(e)}</h1>")

# ==================== ROBLOX OAUTH ====================
@app.get('/auth/roblox')
async def login_roblox(request: Request):
    if not ROBLOX_CLIENT_ID:
        return HTMLResponse(content="<h1>Roblox Login not configured.</h1>")
    
    redirect_uri = str(request.base_url) + "auth/roblox/callback"
    auth_url = (
        "https://apis.roblox.com/oauth/v1/authorize?"
        f"client_id={ROBLOX_CLIENT_ID}&"
        f"redirect_uri={redirect_uri}&"
        "response_type=code&"
        "scope=openid%20profile"
    )
    return RedirectResponse(url=auth_url)

@app.get('/auth/roblox/callback')
async def roblox_callback(request: Request):
    code = request.query_params.get('code')
    if not code:
        return HTMLResponse(content="<h1>Error: Missing authorization code</h1>")

    try:
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
        if resp.status_code != 200:
            return HTMLResponse(content="<h1>Failed to get Roblox token.</h1>")
        
        token_data = resp.json()
        access_token = token_data.get("access_token")
        
        headers = {"Authorization": f"Bearer {access_token}"}
        user_resp = requests.get("https://apis.roblox.com/oauth/v1/userinfo", headers=headers)
        if user_resp.status_code == 200:
            user_info = user_resp.json()
            request.session['user'] = {
                'id': user_info['sub'],
                'name': user_info['name'],
                'email': user_info.get('email', 'No Email Provided'),
                'provider': 'roblox'
            }
            logger.info(f"User logged in via Roblox: {user_info['name']}")
            return RedirectResponse(url="/dashboard")

        return HTMLResponse(content="<h1>Failed to get Roblox user info.</h1>")

    except Exception as e:
        logger.error(f"Roblox Callback Error: {str(e)}")
        return HTMLResponse(content=f"<h1>Authentication Error: {str(e)}</h1>")

@app.get('/auth/logout')
async def logout(request: Request):
    request.session.pop('user', None)
    return RedirectResponse(url="/home")

# ==================== AI MODELS (WITH IMAGE URLS) ====================
MODELS = {
    "auto": {
        "name": "Auto",
        "provider": "Dynamic Router",
        "api": "auto",
        "id": "auto",
        "image": "/images/models/default.png",
        "context": "N/A",
        "speed": 0,
        "intelligence": 0,
        "cost": 0,
        "images": False,
        "cost_per_request": "Adapts",
        "description": "Routes each request to the best model for the job — light models for quick edits, heavyweights for big builds."
    },
    "groq-llama": {
        "name": "Llama 3.3 70B",
        "provider": "Groq / Meta",
        "api": "groq",
        "id": "llama-3.3-70b-versatile",
        "image": "/images/models/meta.png", # Download Meta logo
        "context": "128K tokens",
        "speed": 10,
        "intelligence": 9,
        "cost": 1,
        "images": False,
        "cost_per_request": "Free",
        "description": "Ultra-fast coding model via Groq's free tier. Blazing speed and intelligent enough for 95% of scripts."
    },
    "groq-mixtral": {
        "name": "Mixtral 8x7B",
        "provider": "Groq / Mistral",
        "api": "groq",
        "id": "mixtral-8x7b-32768",
        "image": "/images/models/mistral.png", # Download Mistral logo
        "context": "32K tokens",
        "speed": 8,
        "intelligence": 7,
        "cost": 1,
        "images": False,
        "cost_per_request": "Free",
        "description": "Excellent legacy model for logic and math-heavy scripts. Very fast and completely free."
    },
    "deepseek-v3": {
        "name": "DeepSeek V3",
        "provider": "DeepSeek",
        "api": "openrouter",
        "id": "deepseek/deepseek-chat",
        "image": "/images/models/deepseek.png", # Download DeepSeek logo
        "context": "64K tokens",
        "speed": 9,
        "intelligence": 10,
        "cost": 1,
        "images": False,
        "cost_per_request": "Free",
        "description": "Open-source powerhouse. Easily rivals GPT-4 for coding and is completely free."
    },
    "gemini-2.0-flash": {
        "name": "Gemini 2.0 Flash",
        "provider": "Google",
        "api": "openrouter",
        "id": "google/gemini-2.0-flash-exp",
        "image": "/images/models/google.png", # Download Google logo
        "context": "1M tokens",
        "speed": 10,
        "intelligence": 7,
        "cost": 1,
        "images": True,
        "cost_per_request": "Free",
        "description": "Sub-second latency. Great for rapid prototyping, boilerplate, and utility scripts."
    },
    "qwen-2.5-coder": {
        "name": "Qwen 2.5 Coder 7B",
        "provider": "Alibaba",
        "api": "openrouter",
        "id": "qwen/qwen-2.5-coder-7b-instruct",
        "image": "/images/models/alibaba.png", # Download Alibaba / Qwen logo
        "context": "32K tokens",
        "speed": 8,
        "intelligence": 6,
        "cost": 1,
        "images": False,
        "cost_per_request": "Free",
        "description": "Tiny and lightning fast. Perfect for small Lua utility scripts and basic functions."
    },
    "mistral-7b-instruct": {
        "name": "Mistral 7B",
        "provider": "Mistral",
        "api": "openrouter",
        "id": "mistralai/mistral-7b-instruct",
        "image": "/images/models/mistral.png",
        "context": "8K tokens",
        "speed": 7,
        "intelligence": 5,
        "cost": 1,
        "images": False,
        "cost_per_request": "Free",
        "description": "Lightweight, fast, and completely free. Good for quick drafts."
    },
    "gpt-4o": {
        "name": "GPT-4o",
        "provider": "OpenAI",
        "api": "openrouter",
        "id": "openai/gpt-4o",
        "image": "/images/models/openai.png", # Download OpenAI logo
        "context": "128K tokens",
        "speed": 8,
        "intelligence": 10,
        "cost": 8,
        "images": True,
        "cost_per_request": "$0.03 - $0.10",
        "description": "The gold standard for coding. Excellent for complex game logic and structure (Paid)."
    },
    "claude-3.5-sonnet": {
        "name": "Claude 3.5 Sonnet",
        "provider": "Anthropic",
        "api": "openrouter",
        "id": "anthropic/claude-3.5-sonnet",
        "image": "/images/models/anthropic.png", # Download Anthropic logo
        "context": "200K tokens",
        "speed": 7,
        "intelligence": 10,
        "cost": 6,
        "images": True,
        "cost_per_request": "$0.03 - $0.08",
        "description": "Incredible at following complex formatting rules (Paid)."
    }
}

# ==================== QUEUE ====================
code_queue = deque()
MAX_QUEUE_SIZE = 100

# ==================== PYDANTIC MODELS ====================
class GenerateRequest(BaseModel):
    prompt: str
    model_id: str = "auto"
    destination: str = "ServerScriptService"

class GenerateResponse(BaseModel):
    code: str
    queued: bool
    id: str
    model_used: str

class StatusResponse(BaseModel):
    status: str
    queue_size: int
    models_loaded: int

# ==================== HELPERS ====================
def clean_code(code: str) -> str:
    if not code: return ""
    code = re.sub(r'```lua\s*', '', code)
    code = re.sub(r'```luau\s*', '', code)
    code = re.sub(r'```\s*', '', code)
    return code.strip()

def create_roblox_prompt(user_prompt: str) -> str:
    return f"""You are an expert Roblox Lua developer. Generate ONLY valid, production-ready Roblox Lua code.

CRITICAL RULES:
1. Return ONLY the raw Lua code - no explanations, no markdown.
2. Use modern Roblox APIs (Instance.new, TweenService, etc.).
3. Always use 'local' for variables.
4. Use proper indentation (4 spaces).
5. Include proper error handling with pcall() when appropriate.

User request: {user_prompt}

Lua code:"""

def generate_with_groq(model_id: str, prompt: str) -> str:
    if not GROQ_API_KEY: raise Exception("GROQ_API_KEY missing.")
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": model_id,
        "messages": [{"role": "system", "content": "You are a Roblox Lua expert. Output ONLY Lua code."}, {"role": "user", "content": create_roblox_prompt(prompt)}],
        "temperature": 0.2,
        "max_tokens": 3000
    }
    response = requests.post("https://api.groq.com/openai/v1/chat/completions", json=payload, headers=headers, timeout=30)
    if response.status_code != 200: raise Exception(f"Groq Error: {response.text}")
    return clean_code(response.json()["choices"][0]["message"]["content"])

def generate_with_openrouter(model_id: str, prompt: str) -> str:
    if not OPENROUTER_API_KEY: raise Exception("OPENROUTER_API_KEY missing.")
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": model_id,
        "messages": [{"role": "system", "content": "You are a Roblox Lua expert. Output ONLY Lua code."}, {"role": "user", "content": create_roblox_prompt(prompt)}],
        "temperature": 0.2,
        "max_tokens": 3000
    }
    response = requests.post("https://openrouter.ai/api/v1/chat/completions", json=payload, headers=headers, timeout=60)
    if response.status_code != 200: raise Exception(f"OpenRouter Error: {response.text}")
    return clean_code(response.json()["choices"][0]["message"]["content"])

# ==================== API ENDPOINTS ====================
@app.get("/status", response_model=StatusResponse)
async def get_status():
    return StatusResponse(status="online", queue_size=len(code_queue), models_loaded=len(MODELS))

@app.get("/models")
async def get_models():
    return {"models": MODELS}

@app.post("/generate", response_model=GenerateResponse)
async def generate_code(request: GenerateRequest):
    if not request.prompt:
        raise HTTPException(status_code=400, detail="No prompt provided")
    
    model_id = request.model_id
    if model_id == "auto":
        if GROQ_API_KEY:
            model_id = "groq-llama"
        else:
            model_id = "deepseek-v3"
            
    model_config = MODELS.get(model_id)
    if not model_config:
        raise HTTPException(status_code=400, detail="Invalid model ID")
    
    try:
        if model_config["api"] == "groq":
            code = generate_with_groq(model_config["id"], request.prompt)
        else:
            code = generate_with_openrouter(model_config["id"], request.prompt)
        
        code_id = str(uuid.uuid4())
        script_name = request.prompt[:30].replace(" ", "_").replace("/", "_") + "_Script"
        
        code_queue.append({
            "id": code_id,
            "code": code,
            "scriptName": script_name,
            "destination": request.destination,
            "timestamp": time.time()
        })
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
    if not code_id: return {"success": False}
    for i, item in enumerate(code_queue):
        if item["id"] == code_id:
            code_queue.remove(item)
            return {"success": True}
    return {"success": False}

@app.get("/queue/size")
async def get_queue_size():
    return {"size": len(code_queue)}

# ==================== RUN ====================
if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("🚀 Roblox AI Coder v3.0 - Final Production (Logos)")
    logger.info(f"📊 Loaded {len(MODELS)} models with real stats")
    logger.info("🌐 Server running on port 8000")
    logger.info("=" * 50)
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
