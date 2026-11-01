import React, { useCallback, useEffect, useRef, useState } from "react";
import { Excalidraw } from "@excalidraw/excalidraw";
import "@excalidraw/excalidraw/index.css";

// ---------- helpers ----------
const ROOM_RE = /^\/b\/([A-Za-z0-9_-]{6,64})\/?$/;

function newRoomId() {
  const a = new Uint8Array(9);
  crypto.getRandomValues(a);
  return btoa(String.fromCharCode(...a)).replace(/\+/g, "-").replace(/\//g, "_");
}

function getUsername() {
  try {
    let n = localStorage.getItem("wb-name");
    if (!n) {
      const animals = ["Tiger", "Panda", "Falcon", "Otter", "Lynx", "Koala", "Yak", "Heron"];
      n = animals[Math.floor(Math.random() * animals.length)] + "-" + Math.floor(Math.random() * 900 + 100);
      localStorage.setItem("wb-name", n);
    }
    return n;
  } catch {
    return "Guest";
  }
}

// Same rule Excalidraw uses: higher version wins; on tie, lower versionNonce wins.
function isNewer(incoming, existing) {
  if (!existing) return true;
  if (incoming.version !== existing.version) return incoming.version > existing.version;
  return incoming.versionNonce < existing.versionNonce;
}

function sortedElements(map) {
  return Array.from(map.values()).sort((a, b) => {
    const ia = a.index || "", ib = b.index || "";
    return ia < ib ? -1 : ia > ib ? 1 : 0;
  });
}

function wsUrl(room) {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${location.host}/ws/${room}`;
}

// ---------- home page ----------
function Home() {
  const go = () => (location.href = `/b/${newRoomId()}`);
  return (
    <div style={{ display: "grid", placeItems: "center", height: "100%", background: "#f6f7fb" }}>
      <div style={{ textAlign: "center", padding: 24 }}>
        <h1 style={{ margin: 0, fontSize: 36 }}>Whiteboard</h1>
        <p style={{ color: "#555", maxWidth: 360 }}>
          A free collaborative whiteboard. No sign-up — create a board and share the link.
        </p>
        <button onClick={go} style={btn}>+ New board</button>
      </div>
    </div>
  );
}

const btn = {
  background: "#6965db", color: "#fff", border: 0, borderRadius: 8,
  padding: "12px 22px", fontSize: 16, cursor: "pointer",
};

// ---------- board ----------
function Board({ room }) {
  const [api, setApi] = useState(null);
  const [status, setStatus] = useState("connecting");
  const [online, setOnline] = useState(1);
  const [copied, setCopied] = useState(false);

  const wsRef = useRef(null);
  const versions = useRef(new Map());     // id -> {version, versionNonce} last seen
  const sentFiles = useRef(new Set());
  const pending = useRef(new Map());      // outgoing element changes
  const flushTimer = useRef(null);
  const collaborators = useRef(new Map());
  const username = useRef(getUsername());
  const ready = useRef(false);            // true once initial scene is received

  const send = (obj) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
  };

  const applyRemote = useCallback((elements) => {
    if (!api) return;
    const local = new Map(api.getSceneElementsIncludingDeleted().map((e) => [e.id, e]));
    let changed = false;
    for (const el of elements) {
      if (isNewer(el, local.get(el.id)) && isNewer(el, versions.current.get(el.id))) {
        local.set(el.id, el);
        versions.current.set(el.id, { version: el.version, versionNonce: el.versionNonce });
        changed = true;
      }
    }
    if (changed) api.updateScene({ elements: sortedElements(local) });
  }, [api]);

  // WebSocket lifecycle with auto-reconnect
  useEffect(() => {
    if (!api) return;
    let closed = false;
    let retry = 0;

    const connect = () => {
      const ws = new WebSocket(wsUrl(room));
      wsRef.current = ws;
      ws.onopen = () => {
        retry = 0;
        setStatus("online");
        ws.send(JSON.stringify({ type: "hello", username: username.current }));
        // re-send anything we drew while offline
        const mine = api.getSceneElementsIncludingDeleted();
        if (ready.current && mine.length) {
          ws.send(JSON.stringify({ type: "update", elements: mine }));
        }
      };
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data);
        if (msg.type === "init") {
          applyRemote(msg.elements || []);
          if (msg.files?.length) {
            api.addFiles(msg.files);
            msg.files.forEach((f) => sentFiles.current.add(f.id));
          }
          ready.current = true;
        } else if (msg.type === "update") {
          applyRemote(msg.elements || []);
        } else if (msg.type === "files") {
          api.addFiles(msg.files);
          msg.files.forEach((f) => sentFiles.current.add(f.id));
        } else if (msg.type === "presence") {
          setOnline(msg.count);
          if (msg.left) {
            collaborators.current.delete(msg.left);
            api.updateScene({ collaborators: new Map(collaborators.current) });
          }
        } else if (msg.type === "pointer") {
          collaborators.current.set(msg.cid, {
            username: msg.username,
            pointer: msg.pointer,
            button: msg.button,
          });
          api.updateScene({ collaborators: new Map(collaborators.current) });
        }
      };
      ws.onclose = () => {
        if (closed) return;
        setStatus("offline");
        retry = Math.min(retry + 1, 6);
        setTimeout(connect, 500 * 2 ** retry);
      };
    };
    connect();
    return () => {
      closed = true;
      wsRef.current?.close();
    };
  }, [api, room, applyRemote]);

  const flush = () => {
    flushTimer.current = null;
    if (!pending.current.size) return;
    send({ type: "update", elements: Array.from(pending.current.values()) });
    pending.current.clear();
  };

  const onChange = (elements, _appState, files) => {
    if (!ready.current) return;
    for (const el of elements) {
      if (isNewer(el, versions.current.get(el.id))) {
        versions.current.set(el.id, { version: el.version, versionNonce: el.versionNonce });
        pending.current.set(el.id, el);
      }
    }
    if (pending.current.size && !flushTimer.current) {
      flushTimer.current = setTimeout(flush, 60);
    }
    // images / embedded files
    const newFiles = Object.values(files || {}).filter((f) => !sentFiles.current.has(f.id));
    if (newFiles.length) {
      newFiles.forEach((f) => sentFiles.current.add(f.id));
      send({ type: "files", files: newFiles });
    }
  };

  const lastPtr = useRef(0);
  const onPointerUpdate = ({ pointer, button }) => {
    const now = Date.now();
    if (now - lastPtr.current < 50) return;
    lastPtr.current = now;
    send({ type: "pointer", pointer, button, username: username.current });
  };

  const share = async () => {
    try {
      if (navigator.share) await navigator.share({ title: "Whiteboard", url: location.href });
      else await navigator.clipboard.writeText(location.href);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {}
  };

  const dot = { online: "#2bb673", connecting: "#f0ad4e", offline: "#d9534f" }[status];

  return (
    <div style={{ height: "100%" }}>
      <Excalidraw
        excalidrawAPI={setApi}
        onChange={onChange}
        onPointerUpdate={onPointerUpdate}
        isCollaborating={true}
        renderTopRightUI={() => (
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span title={status} style={{ fontSize: 12, color: "#555", display: "flex", alignItems: "center", gap: 4 }}>
              <span style={{ width: 8, height: 8, borderRadius: 8, background: dot, display: "inline-block" }} />
              {online}
            </span>
            <button onClick={share} style={{ ...btn, padding: "6px 12px", fontSize: 13 }}>
              {copied ? "Copied!" : "Share"}
            </button>
          </div>
        )}
      />
    </div>
  );
}

export default function App() {
  const m = location.pathname.match(ROOM_RE);
  return m ? <Board room={m[1]} /> : <Home />;
}
