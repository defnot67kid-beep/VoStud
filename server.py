"""
Roblox AI Coder - Modular Server
Supports Home (/home), Signup (/signup) & Dashboard (/dashboard)
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
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== CONFIGURATION ====================
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# ==================== MODELS ====================
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

# ==================== QUEUE ====================
code_queue = deque()
MAX_QUEUE_SIZE = 100

# ==================== Pydantic Models ====================
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

# ==================== FastAPI App ====================
app = FastAPI(title="Roblox AI Coder", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== SERVE STATIC FILES ====================
app.mount("/static", StaticFiles(directory="web"), name="static")

# ROOT REDIRECTS TO HOME
@app.get("/", response_class=RedirectResponse)
async def root():
    return RedirectResponse(url="/home")

# HOME PAGE
@app.get("/home", response_class=HTMLResponse)
async def serve_home():
    html_path = os.path.join("web", "home.html")
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Home page not found.</h1>")

# SIGNUP PAGE
@app.get("/signup", response_class=HTMLResponse)
async def serve_signup():
    html_path = os.path.join("web", "signup.html")
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Signup page not found.</h1>")

# DASHBOARD PAGE
@app.get("/dashboard", response_class=HTMLResponse)
async def serve_dashboard():
    html_path = os.path.join("web", "dashboard.html")
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Dashboard page not found.</h1>")

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

# ==================== ENDPOINTS ====================
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
    logger.info("🚀 Roblox AI Coder v3.0")
    logger.info(f"📊 Loaded {len(MODELS)} models")
    logger.info("🌐 Server running on port 8000")
    logger.info("=" * 50)
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
