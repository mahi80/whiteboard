# Whiteboard

A free, self-hostable collaborative whiteboard. It uses Excalidraw for the canvas and a Python (FastAPI) server for live sync.

- No login. Create a board, share the link, and anyone with the link can draw.
- Live sync over WebSockets, with collaborator cursors and an online count.
- Boards save automatically to SQLite (local) or Postgres (cloud).
- Images pasted onto the board sync too (up to 4 MB each).
- Export a board: `GET /api/board/<id>` downloads an `.excalidraw` file.

## Deploy free on Render

1. Sign in to Render with GitHub, then go to **New → Blueprint** and pick `mahi80/whiteboard`. Render reads `render.yaml`. No card is needed.
2. Paste the Neon connection strings (Neon console → project `fragrant-morning-93689045` → branch `production` → Connect):
   - `DATABASE_URL`: the **pooled** string (host contains `-pooler`)
   - `DATABASE_URL_UNPOOLED`: the direct string (optional)

   Free Render containers lose their disk on every restart, so without a database your boards disappear.
3. Wait about 5 minutes for the first build, then open `https://whiteboard-xxxx.onrender.com`.

On the free tier the service sleeps after 15 minutes idle. The first visit after that takes about a minute to wake it up.

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
