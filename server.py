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
oauth.register(
    name='google',
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={
        'scope': 'openid email profile'
    }
)

# Roblox OAuth Config (Manual config as Roblox doesn't have a standard well-known endpoint)
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

# 1. Initiate Google Login
@app.get('/auth/google')
async def login_google(request: Request):
    redirect_uri = request.url_for('auth_callback').include_query_params(provider='google')
    return await oauth.google.authorize_redirect(request, str(redirect_uri))

# 2. Initiate Roblox Login
@app.get('/auth/roblox')
async def login_roblox(request: Request):
    redirect_uri = request.url_for('auth_callback').include_query_params(provider='roblox')
    return await oauth.roblox.authorize_redirect(request, str(redirect_uri))

# 3. OAuth Callback (Where the user is sent back after login)
@app.get('/auth/callback')
async def auth_callback(request: Request, provider: str = None):
    if not provider:
        return HTMLResponse(content="<h1>Error: Missing provider</h1>")

    try:
        # Handle Google Callback
        if provider == 'google':
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

        # Handle Roblox Callback
        elif provider == 'roblox':
            token = await oauth.roblox.authorize_access_token(request)
            # Roblox requires a separate call to get user info
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

# 4. Logout
@app.get('/auth/logout')
async def logout(request: Request):
    request.session.pop('user', None)
    return RedirectResponse(url="/home")

# ==================== API ENDPOINTS ====================
# (Your existing /status, /generate, /queue/next endpoints go here unchanged)
# ...

# ==================== RUN ====================
if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("🚀 Roblox AI Coder v3.0 - OAuth Enabled")
    logger.info("🌐 Server running on port 8000")
    logger.info("=" * 50)
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
