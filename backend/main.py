"""
Whiteboard server — FastAPI + WebSockets.

* Serves the built Excalidraw frontend.
* /ws/{room}: live sync. Server keeps the merged board per room and saves it.
* No login: anyone with the room link can edit.
"""
import asyncio
import json
import os
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from storage import Storage

ROOM_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}$")
DIST = Path(os.getenv("FRONTEND_DIST", Path(__file__).resolve().parent.parent / "frontend" / "dist"))
SAVE_EVERY = float(os.getenv("SAVE_EVERY_SECONDS", "3"))
MAX_FILE_BYTES = int(os.getenv("MAX_FILE_BYTES", str(4 * 1024 * 1024)))  # per image

store: Storage | None = None


class Room:
    def __init__(self, room_id: str, data: dict):
        self.id = room_id
        self.elements: dict = data.get("elements", {})
        self.files: dict = data.get("files", {})
        self.clients: dict[str, WebSocket] = {}
        self.dirty = False

    def merge(self, incoming: list) -> list:
        """Keep the newest version of each element; return the ones that changed."""
        accepted = []
        for el in incoming:
            if not isinstance(el, dict) or "id" not in el:
                continue
            cur = self.elements.get(el["id"])
            v, n = el.get("version", 0), el.get("versionNonce", 0)
            if cur is None or v > cur.get("version", 0) or (
                v == cur.get("version", 0) and n < cur.get("versionNonce", 0)
            ):
                self.elements[el["id"]] = el
                accepted.append(el)
        if accepted:
            self.dirty = True
        return accepted

    def snapshot(self):
        return {"elements": self.elements, "files": self.files}

    async def broadcast(self, msg: dict, exclude: str | None = None):
        text = json.dumps(msg, separators=(",", ":"))
        for cid, ws in list(self.clients.items()):
            if cid == exclude:
                continue
            try:
                await ws.send_text(text)
            except Exception:
                self.clients.pop(cid, None)


rooms: dict[str, Room] = {}
rooms_lock = asyncio.Lock()


async def save_room(room: Room):
    if room.dirty:
        room.dirty = False
        try:
            await run_in_threadpool(store.save, room.id, room.snapshot())
        except Exception as e:  # keep running; retry next tick
            room.dirty = True
            print(f"[save] {room.id} failed: {e}")


async def saver_loop():
    while True:
        await asyncio.sleep(SAVE_EVERY)
        for room in list(rooms.values()):
            await save_room(room)


@asynccontextmanager
async def lifespan(_app):
    global store
    store = Storage()
    print(f"[storage] using {store.kind}")
    task = asyncio.create_task(saver_loop())
    yield
    task.cancel()
    for room in list(rooms.values()):
        await save_room(room)


app = FastAPI(title="Whiteboard", lifespan=lifespan)


async def get_room(room_id: str) -> Room:
    async with rooms_lock:
        room = rooms.get(room_id)
        if room is None:
            data = await run_in_threadpool(store.load, room_id)
            room = rooms[room_id] = Room(room_id, data)
        return room


@app.get("/healthz")
def healthz():
    return {"ok": True, "storage": store.kind if store else None, "rooms_open": len(rooms)}


@app.get("/api/board/{room_id}")
async def export_board(room_id: str):
    """Download a board as an .excalidraw JSON file."""
    if not ROOM_RE.match(room_id):
        raise HTTPException(400, "bad room id")
    room = await get_room(room_id)
    return JSONResponse(
        {
            "type": "excalidraw",
            "version": 2,
            "source": "whiteboard",
            "elements": [e for e in room.elements.values() if not e.get("isDeleted")],
            "appState": {},
            "files": room.files,
        },
        headers={"Content-Disposition": f'attachment; filename="{room_id}.excalidraw"'},
    )


@app.websocket("/ws/{room_id}")
async def ws_room(ws: WebSocket, room_id: str):
    if not ROOM_RE.match(room_id):
        await ws.close(code=1008)
        return
    await ws.accept()
    room = await get_room(room_id)
    cid = uuid.uuid4().hex[:12]
    room.clients[cid] = ws

    await ws.send_text(json.dumps({
        "type": "init",
        "elements": list(room.elements.values()),
        "files": list(room.files.values()),
    }))
    await room.broadcast({"type": "presence", "count": len(room.clients)})

    try:
        while True:
            msg = json.loads(await ws.receive_text())
            t = msg.get("type")
            if t == "update":
                accepted = room.merge(msg.get("elements") or [])
                if accepted:
                    await room.broadcast({"type": "update", "elements": accepted}, exclude=cid)
            elif t == "files":
                ok = []
                for f in msg.get("files") or []:
                    if isinstance(f, dict) and f.get("id") and len(f.get("dataURL", "")) <= MAX_FILE_BYTES * 1.4:
                        room.files[f["id"]] = f
                        ok.append(f)
                if ok:
                    room.dirty = True
                    await room.broadcast({"type": "files", "files": ok}, exclude=cid)
            elif t == "pointer":
                await room.broadcast({
                    "type": "pointer", "cid": cid,
                    "pointer": msg.get("pointer"), "button": msg.get("button"),
                    "username": str(msg.get("username", "Guest"))[:40],
                }, exclude=cid)
    except (WebSocketDisconnect, RuntimeError, ValueError):
        pass
    finally:
        room.clients.pop(cid, None)
        await room.broadcast({"type": "presence", "count": len(room.clients), "left": cid})
        if not room.clients:
            await save_room(room)
            async with rooms_lock:
                if not room.clients and not room.dirty:
                    rooms.pop(room_id, None)


# ---------- frontend (SPA) ----------
if (DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.get("/{path:path}")
def spa(path: str):
    f = DIST / path
    if path and f.is_file() and DIST in f.resolve().parents:
        return FileResponse(f)
    index = DIST / "index.html"
    if not index.exists():
        return JSONResponse({"error": "frontend not built — run `npm run build` in frontend/"}, 503)
    return FileResponse(index)
