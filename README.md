# Roblox AI Coder

A modular Roblox script generation tool using AI. Write prompts in the web UI, and scripts appear instantly in your Roblox Studio.

## How to Run Locally
1. Install Python requirements: `pip install -r requirements.txt`
2. Create a `.env` file with `GROQ_API_KEY=` and/or `OPENROUTER_API_KEY=`.
3. Run the server: `python server.py`
4. Open `web/index.html` in your browser.
5. Install the `roblox-plugin` folder into your Roblox Studio Plugins folder.

## Deploying 24/7 (Render)
1. Push this repo to GitHub.
2. Create a new **Web Service** on Render.
3. Point it to your GitHub repo.
4. Set Build Command: `pip install -r requirements.txt`
5. Set Start Command: `gunicorn -w 1 -k uvicorn.workers.UvicornWorker server:app`
6. Add your `GROQ_API_KEY` and `OPENROUTER_API_KEY` to Render's **Environment Variables** (do NOT put them in `.env` on GitHub).

> ⚠️ **Important:** Never commit your `.env` file to GitHub. It is already ignored via `.gitignore`.
