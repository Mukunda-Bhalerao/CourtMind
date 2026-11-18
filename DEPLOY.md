# Deploying CourtMind (Render free tier)

CourtMind's web app is a FastAPI server. It is deployed to **[Render](https://render.com)** as a
free Python web service, straight from GitHub. The repo includes a `render.yaml` blueprint,
so Render configures itself.

**Why Render rather than Vercel:** Vercel runs Python only as short-lived serverless
functions, which suit small APIs, not a full FastAPI app with templates, uploads and a
multi-second simulation. Render runs it as a normal long-lived server for free.

## What's in the repo for deployment

| File | Purpose |
|---|---|
| `render.yaml` | Render Blueprint: build/start commands, health check, env vars |
| `court_mind_web/requirements.txt` | Minimal pinned dependencies for the website only (fast build) |
| `.python-version` | Pins Python 3.11.9 |
| `.env.example` | Every supported environment variable, documented |

Start command (already in `render.yaml`):

```bash
uvicorn court_mind_web.main:app --host 0.0.0.0 --port $PORT
```

## Steps

1. **Push to GitHub.** Commit everything and push `main`. `.env` is git-ignored, so your keys stay local.
2. **Create a Render account** at https://render.com and sign in with GitHub.
3. **New → Blueprint.** Pick the CourtMind repository. Render reads `render.yaml` and shows one web service called `courtmind` on the Free plan.
4. **Fill in the secret env vars** it asks for. All of them are optional, so you can leave them blank:
   - `SERPER_API_KEY`: Google search context in the report's Research tab
   - `KANOON_API_KEY`: Indian Kanoon precedents in the Research tab
   - `OLLAMA_API_KEY`: only if you enable Ollama Cloud (see below)
5. **Apply.** The first build takes about 2–3 minutes. Your site will be live at `https://courtmind.onrender.com`, or a similar name if that one is taken.
6. Open `https://<your-app>.onrender.com/healthz` and you should see `{"status":"ok",...}`.

After this, every push to `main` redeploys automatically.

> **Manual alternative (without the blueprint):** New → Web Service → pick the repo, then:
> Runtime **Python 3**, Build command `pip install -r court_mind_web/requirements.txt`,
> Start command `uvicorn court_mind_web.main:app --host 0.0.0.0 --port $PORT`,
> Health check path `/healthz`, Instance type **Free**, env var `LLM_EXTRACTION=false`.

## LLM fact extraction in the cloud (optional)

Render has no Ollama server, so the deploy uses `LLM_EXTRACTION=false`, which means the
built-in keyword extractor. All the legal reasoning after extraction is rule-based and runs
exactly the same either way.

To use an LLM anyway, create an API key at https://ollama.com and set these on Render:

```
LLM_EXTRACTION=true
OLLAMA_BASE_URL=https://ollama.com
OLLAMA_MODEL=gpt-oss:120b
OLLAMA_API_KEY=<your key>
```

If the LLM call fails or times out (`OLLAMA_TIMEOUT`, 45 s), the app falls back to keyword extraction automatically.

## Free-tier notes

- The service **sleeps after 15 minutes without traffic**. The first request after that takes about 30–60 seconds to wake it. The loading screen tells visitors about this.
- 512 MB RAM and 750 free instance hours a month, which is plenty for one always-on service.

## Run locally

```bash
pip install -r court_mind_web/requirements.txt
```

```bash
uvicorn court_mind_web.main:app --reload
```

Then open http://localhost:8000.
