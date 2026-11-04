# Whiteboard

A free, self-hostable collaborative whiteboard. It uses Excalidraw for the canvas and a Python (FastAPI) server for live sync.

- No login. Create a board, share the link, and anyone with the link can draw.
- Live sync over WebSockets, with collaborator cursors and an online count.
- Boards save automatically to SQLite (local) or Postgres (cloud).
- Images pasted onto the board sync too (up to 4 MB each).
- Export a board: `GET /api/board/<id>` downloads an `.excalidraw` file.

## Live

**https://whiteboard-m7n7.onrender.com** (Render free tier)

Open it, tap **+ New board**, then **Share** to send the link. Nobody needs to log in.

### Using it for interviews
- **Open the link 1–2 minutes before the call.** The free server sleeps after 15 minutes idle, and the first visit takes about 50 seconds to wake it.
- While people are drawing, the server stays awake and everything syncs live.
- **Boards are temporary.** No database is configured, so a board is wiped about 15 minutes after everyone leaves, or on any redeploy. To keep a drawing, use **☰ menu → Save to… / Export image** before closing.

## Deploy free on Render

1. Sign in to Render, go to **New → Blueprint**, and enter `https://github.com/mahi80/whiteboard`. Render reads `render.yaml`. No card is needed.
2. Click **Deploy Blueprint**. The first build takes a few minutes. Every push to `main` redeploys automatically.

### Optional: keep boards permanently (Neon Postgres)
By default the app uses SQLite on the container disk, and free Render containers lose that disk on every restart. To make boards permanent:
1. Neon console → project `fragrant-morning-93689045` → branch `production` → **Connect**. Copy the **pooled** string (its host contains `-pooler`).
2. Render → whiteboard service → **Environment** → add `DATABASE_URL` = that string (optionally `DATABASE_URL_UNPOOLED` = the direct string) → **Save and deploy**.
3. Check `/healthz`. It should show `"storage":"postgres"`.

No code changes are needed.

## Run locally

**With Docker**
```bash
docker compose up --build      # http://localhost:8000  (boards saved in ./data)
```

**Without Docker**
```bash
cd frontend && npm install && npm run build && cd ..
pip install -r backend/requirements.txt
cd backend && uvicorn main:app --host 0.0.0.0 --port 8000
```
Other people on your Wi-Fi can open `http://<your-ip>:8000`.

**Dev mode (hot reload):** run `uvicorn main:app --reload` in `backend/` and `npm run dev` in `frontend/`, then open http://localhost:5173.

## Other free hosts
Any host that runs a Docker container with WebSockets works: Fly.io, Koyeb, Railway (trial), or an Oracle Cloud free VM with `docker compose up -d`. Heroku works too but has no free tier.

## Config (env vars)
| Var | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | – | Postgres URL. If unset, SQLite is used |
| `SQLITE_PATH` | `data/boards.db` | SQLite file location |
| `SAVE_EVERY_SECONDS` | `3` | How often changed boards are saved |
| `MAX_FILE_BYTES` | `4194304` | Max size per pasted image |
| `PORT` | `8000` | Port to listen on |

## How it works
```
Browser (Excalidraw) ──ws /ws/<room>──▶ FastAPI
   onChange → sends changed elements     merges by element version (newest wins)
   receives others' changes → updateScene  broadcasts to the room, saves every 3s
```
Rooms are random 12-character IDs. Anyone who knows the link can edit, the same way Excalidraw share links work.
