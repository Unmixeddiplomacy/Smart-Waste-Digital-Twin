import os
import sys
import json
import random
import shutil
import asyncio
import datetime
import tempfile
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Resolve project paths relative to this file
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
STATIC_DIR = os.path.join(PROJECT_ROOT, "web_twin", "static")
INDEX_HTML_PATH = os.path.join(STATIC_DIR, "index.html")

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

try:
    from backend.database import (
        init_db,
        add_sort_event,
        get_recent_events,
        get_bin_statuses,
        get_statistics,
        reset_all,
        add_system_log,
    )
except ImportError:
    from database import (
        init_db,
        add_sort_event,
        get_recent_events,
        get_bin_statuses,
        get_statistics,
        reset_all,
        add_system_log,
    )

try:
    from ai_model.inference import WasteClassifier
except Exception:
    WasteClassifier = None

# Global state
classifier = None
simulation_running = False
simulation_task = None

WASTE_CLASSES = ["cardboard", "glass", "metal", "paper", "plastic", "trash"]
WASTE_WEIGHTS = [0.2, 0.1, 0.15, 0.25, 0.15, 0.15]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize SQLite DB and gracefully load the trained WasteClassifier on startup."""
    global classifier, simulation_running, simulation_task

    init_db()

    if WasteClassifier is not None:
        try:
            classifier = WasteClassifier()
        except FileNotFoundError as e:
            print(f"WARNING: {e} — Server running without AI model.")
            classifier = None
        except Exception as e:
            print(f"WARNING: Could not load WasteClassifier ({e}) — Server running without AI model.")
            classifier = None
    else:
        print("WARNING: WasteClassifier import unavailable — Server running without AI model.")
        classifier = None

    print("Server started on http://localhost:8000")
    yield

    # Stop background simulation task cleanly on shutdown
    simulation_running = False
    if simulation_task is not None and not simulation_task.done():
        simulation_task.cancel()
        try:
            await simulation_task
        except asyncio.CancelledError:
            pass
    simulation_task = None


app = FastAPI(
    title="Smart Waste Sorting Digital Twin",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static directory at /static (never at /, which would shadow API routes)
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ConnectionManager:
    """Manages active WebSocket connections and JSON broadcasting."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"Client connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        print(f"Client disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        dead = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                dead.append(connection)
        for d in dead:
            self.disconnect(d)

    async def send_personal(self, websocket: WebSocket, message: dict):
        try:
            await websocket.send_json(message)
        except Exception:
            self.disconnect(websocket)


manager = ConnectionManager()


# ---------------------------------------------------------------------------
# REST Endpoints
# ---------------------------------------------------------------------------


@app.get("/")
async def serve_index():
    """Serve the main Digital Twin dashboard index.html."""
    if os.path.exists(INDEX_HTML_PATH):
        return FileResponse(INDEX_HTML_PATH)
    return HTMLResponse(content="<h1>index.html not found</h1>", status_code=404)


@app.get("/api/health")
async def health_check():
    """Return server health and AI model load status."""
    return {
        "status": "ok",
        "model_loaded": classifier is not None,
        "timestamp": datetime.datetime.now().isoformat(),
    }


@app.get("/api/stats")
async def api_stats():
    """Return aggregated sorting statistics."""
    return await asyncio.to_thread(get_statistics)


@app.get("/api/bins")
async def api_bins():
    """Return current status of all 6 waste bins."""
    return await asyncio.to_thread(get_bin_statuses)


@app.get("/api/events")
async def api_events(limit: int = 50):
    """Return recent sorting events."""
    return await asyncio.to_thread(get_recent_events, limit)


@app.post("/api/predict")
async def api_predict(file: UploadFile = File(...)):
    """Classify an uploaded waste image, store event in DB, and broadcast via WebSocket."""
    if classifier is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    suffix = os.path.splitext(file.filename or "upload.jpg")[1] or ".jpg"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp_path = tmp.name

    try:
        shutil.copyfileobj(file.file, tmp)
        tmp.close()

        result = await asyncio.to_thread(classifier.predict, temp_path)
        detected_class = result["class"]
        confidence = result["confidence"]

        event_id = await asyncio.to_thread(
            add_sort_event,
            detected_class,
            confidence,
            detected_class,
            True,
        )

        event_payload = {
            "id": event_id,
            "detected_class": detected_class,
            "confidence": confidence,
            "assigned_bin": detected_class,
            "success": True,
            "timestamp": datetime.datetime.now().isoformat(),
        }

        await manager.broadcast({"type": "sort_event", "data": event_payload})
        await manager.broadcast(
            {"type": "stats_update", "data": await asyncio.to_thread(get_statistics)}
        )
        await manager.broadcast(
            {"type": "bins_update", "data": await asyncio.to_thread(get_bin_statuses)}
        )

        return JSONResponse(
            content={
                "event_id": event_id,
                **result,
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prediction failed: {e}")
    finally:
        try:
            if not tmp.closed:
                tmp.close()
        except Exception:
            pass
        if os.path.exists(temp_path):
            os.remove(temp_path)


@app.post("/api/reset")
async def api_reset():
    """Reset all sorting events and bin counts."""
    await asyncio.to_thread(reset_all)
    await manager.broadcast(
        {"type": "stats_update", "data": await asyncio.to_thread(get_statistics)}
    )
    await manager.broadcast(
        {"type": "bins_update", "data": await asyncio.to_thread(get_bin_statuses)}
    )
    return {"status": "reset"}


async def simulation_loop():
    """Background asyncio task generating simulated waste sorting events."""
    global simulation_running
    try:
        while simulation_running:
            waste_class = random.choices(WASTE_CLASSES, weights=WASTE_WEIGHTS, k=1)[0]
            confidence = round(random.uniform(0.70, 0.99), 4)

            # Simulate classification accuracy (~92%)
            if random.random() > 0.92:
                wrong_classes = [c for c in WASTE_CLASSES if c != waste_class]
                detected = random.choice(wrong_classes)
                confidence = round(random.uniform(0.40, 0.75), 4)
            else:
                detected = waste_class

            success = detected == waste_class

            # Record in database
            event_id = add_sort_event(detected, confidence, detected, success)

            # Broadcast to all connected WebSocket clients
            await manager.broadcast(
                {
                    "type": "sort_event",
                    "data": {
                        "id": event_id,
                        "detected_class": detected,
                        "confidence": confidence,
                        "assigned_bin": detected,
                        "success": success,
                        "timestamp": datetime.datetime.now().isoformat(),
                    },
                }
            )

            # Also broadcast updated stats and bin status
            await manager.broadcast({"type": "stats_update", "data": get_statistics()})
            await manager.broadcast({"type": "bins_update", "data": get_bin_statuses()})

            await asyncio.sleep(random.uniform(2.0, 4.0))
    except asyncio.CancelledError:
        pass


@app.post("/api/simulate/start")
async def api_simulate_start():
    """Start the background simulation loop (idempotent — prevents duplicate tasks)."""
    global simulation_running, simulation_task
    simulation_running = True
    if simulation_task is None or simulation_task.done():
        simulation_task = asyncio.create_task(simulation_loop())
    return {"status": "started"}


@app.post("/api/simulate/stop")
async def api_simulate_stop():
    """Stop the background simulation loop cleanly."""
    global simulation_running, simulation_task
    simulation_running = False
    if simulation_task is not None and not simulation_task.done():
        simulation_task.cancel()
        try:
            await simulation_task
        except asyncio.CancelledError:
            pass
    simulation_task = None
    return {"status": "stopped"}


# ---------------------------------------------------------------------------
# WebSocket Endpoint
# ---------------------------------------------------------------------------


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Stream real-time sorting events and status updates to connected clients."""
    await manager.connect(websocket)
    try:
        bins = await asyncio.to_thread(get_bin_statuses)
        stats = await asyncio.to_thread(get_statistics)
        await manager.send_personal(
            websocket,
            {
                "type": "init",
                "bins": bins,
                "stats": stats,
                "data": {"bins": bins, "stats": stats},
            },
        )

        while True:
            raw_msg = await websocket.receive_text()
            try:
                payload = json.loads(raw_msg)
            except json.JSONDecodeError:
                continue

            msg_type = payload.get("type")
            if msg_type == "spawn":
                await manager.broadcast(
                    {"type": "spawn", "data": payload.get("waste", payload)}
                )
            elif msg_type == "detection":
                await manager.broadcast(
                    {
                        "type": "detection",
                        "data": {
                            "detected_class": payload.get("class"),
                            "confidence": payload.get("confidence", 0.0),
                        },
                    }
                )
            elif msg_type == "sorted":
                detected_class = payload.get("class", "trash")
                confidence = float(payload.get("confidence", 0.9))
                assigned_bin = payload.get("bin", detected_class)
                success = bool(payload.get("success", True))

                event_id = await asyncio.to_thread(
                    add_sort_event,
                    detected_class,
                    confidence,
                    assigned_bin,
                    success,
                )
                await manager.broadcast(
                    {
                        "type": "sort_event",
                        "data": {
                            "id": event_id,
                            "detected_class": detected_class,
                            "confidence": confidence,
                            "assigned_bin": assigned_bin,
                            "success": success,
                            "timestamp": datetime.datetime.now().isoformat(),
                        },
                    }
                )
                await manager.broadcast(
                    {
                        "type": "stats_update",
                        "data": await asyncio.to_thread(get_statistics),
                    }
                )
                await manager.broadcast(
                    {
                        "type": "bins_update",
                        "data": await asyncio.to_thread(get_bin_statuses),
                    }
                )
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
