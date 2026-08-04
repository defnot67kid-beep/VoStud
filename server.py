"""
Roblox AI Coder - Full OAuth Server
Handles Real Google & Roblox Login
"""

import os
import re
import uuid
import time
import logging
import requests
import uvicorn
from collections import deque
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from authlib.integrations.starlette_client import OAuth
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
SESSION_SECRET = os.getenv("SESSION_SECRET")

# ==================== FASTAPI SETUP ====================
app = FastAPI(title="Roblox AI Coder", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add Session Middleware to handle cookies/logins
if SESSION_SECRET:
    app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)

# ==================== OAUTH SETUP ====================
oauth = OAuth()

# Google OAuth Config
if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
    oauth.register(
        name='google',
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={
            'scope': 'openid email profile'
        }
    )
else:
    logger.warning("⚠️ Google OAuth credentials missing. Google login will be disabled.")

# Roblox OAuth Config
if ROBLOX_CLIENT_ID and ROBLOX_CLIENT_SECRET:
    oauth.register(
        name='roblox',
        client_id=ROBLOX_CLIENT_ID,
        client_secret=ROBLOX_CLIENT_SECRET,
        authorize_url='https://apis.roblox.com/oauth/v1/authorize',
        access_token_url='https://apis.roblox.com/oauth/v1/token',
        client_kwargs={
            'scope': 'openid profile',
            'token_endpoint_auth_method': 'client_secret_post'
        }
    )
else:
    logger.warning("⚠️ Roblox OAuth credentials missing. Roblox login will be disabled.")

# ==================== SERVE STATIC FILES ====================
app.mount("/static", StaticFiles(directory="web"), name="static")

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
    # If user is already logged in, send them to dashboard
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

# ==================== OAUTH AUTH ROUTES ====================

@app.get('/auth/google')
async def login_google(request: Request):
    if not GOOGLE_CLIENT_ID:
        return HTMLResponse(content="<h1>Google Login is not configured.</h1>")
    redirect_uri = request.url_for('auth_callback').include_query_params(provider='google')
    return await oauth.google.authorize_redirect(request, str(redirect_uri))

@app.get('/auth/roblox')
async def login_roblox(request: Request):
    if not ROBLOX_CLIENT_ID:
        return HTMLResponse(content="<h1>Roblox Login is not configured.</h1>")
    redirect_uri = request.url_for('auth_callback').include_query_params(provider='roblox')
    return await oauth.roblox.authorize_redirect(request, str(redirect_uri))

@app.get('/auth/callback')
async def auth_callback(request: Request, provider: str = None):
    if not provider:
        return HTMLResponse(content="<h1>Error: Missing provider</h1>")

    try:
        if provider == 'google':
            if not GOOGLE_CLIENT_ID:
                return HTMLResponse(content="<h1>Google Login is not configured.</h1>")
            token = await oauth.google.authorize_access_token(request)
            user_info = token.get('userinfo')
            if user_info:
                request.session['user'] = {
                    'id': user_info['sub'],
                    'name': user_info['name'],
                    'email': user_info['email'],
                    'provider': 'google'
                }
                logger.info(f"User logged in via Google: {user_info['email']}")
                return RedirectResponse(url="/dashboard")

        elif provider == 'roblox':
            if not ROBLOX_CLIENT_ID:
                return HTMLResponse(content="<h1>Roblox Login is not configured.</h1>")
            token = await oauth.roblox.authorize_access_token(request)
            headers = {'Authorization': f'Bearer {token["access_token"]}'}
            resp = requests.get('https://apis.roblox.com/oauth/v1/userinfo', headers=headers)
            if resp.status_code == 200:
                user_info = resp.json()
                request.session['user'] = {
                    'id': user_info['sub'],
                    'name': user_info['name'],
                    'email': user_info.get('email', 'No Email Provided'),
                    'provider': 'roblox'
                }
                logger.info(f"User logged in via Roblox: {user_info['name']}")
                return RedirectResponse(url="/dashboard")
        
        return HTMLResponse(content="<h1>Authentication failed: Could not get user info.</h1>")

    except Exception as e:
        logger.error(f"OAuth Callback Error: {str(e)}")
        return HTMLResponse(content=f"<h1>Authentication Error: {str(e)}</h1>")

@app.get('/auth/logout')
async def logout(request: Request):
    request.session.pop('user', None)
    return RedirectResponse(url="/home")

# ==================== YOUR API ENDPOINTS ====================
# (These are your existing endpoints, kept unchanged)

MODELS = {
    "groq-llama": {
        "name": "Llama 3.3 70B",
        "provider": "Meta (via Groq)",
        "api": "groq",
        "id": "llama-3.3-70b-versatile",
        "description": "Ultra-fast coding model via Groq."
    },
    "gpt-4o": {
        "name": "GPT-4o",
        "provider": "OpenAI (via OpenRouter)",
        "api": "openrouter",
        "id": "openai/gpt-4o",
        "description": "#1 Coding model. Excellent for complex game logic."
    }
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

class StatusResponse(BaseModel):
    status: str
    queue_size: int
    models_loaded: int

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
    
    model_config = MODELS.get(request.model_id)
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
    logger.info("🚀 Roblox AI Coder v3.0 - OAuth Enabled")
    logger.info("🌐 Server running on port 8000")
    logger.info("=" * 50)
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
