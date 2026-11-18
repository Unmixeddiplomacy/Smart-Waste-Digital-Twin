import os
import sys
import json
import uuid
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
DATASET_DIR = os.path.join(PROJECT_ROOT, "ai_model", "dataset")
# Store uploaded images in system temp dir so uvicorn --reload never restarts on upload
UPLOADS_DIR = os.path.join(tempfile.gettempdir(), "smart_waste_uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

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
dataset_samples: dict[str, list[tuple[str, str]]] = {}

WASTE_CLASSES = ["cardboard", "glass", "metal", "paper", "plastic", "trash"]
WASTE_WEIGHTS = [0.2, 0.1, 0.15, 0.25, 0.15, 0.15]
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


def _scan_dataset_images() -> dict[str, list[tuple[str, str]]]:
    """Index available real TrashNet images per class for live AI simulation."""
    samples: dict[str, list[tuple[str, str]]] = {}
    if not os.path.isdir(DATASET_DIR):
        return samples
    for cls in WASTE_CLASSES:
        cls_dir = os.path.join(DATASET_DIR, cls)
        if not os.path.isdir(cls_dir):
            continue
        entries = []
        for fn in os.listdir(cls_dir):
            if fn.lower().endswith(IMAGE_EXTENSIONS):
                entries.append((os.path.join(cls_dir, fn), f"/dataset/{cls}/{fn}"))
        if entries:
            samples[cls] = entries
    return samples


def _cleanup_old_uploads(max_keep: int = 25) -> None:
    """Keep only the most recent uploaded images on disk."""
    try:
        files = [
            os.path.join(UPLOADS_DIR, f)
            for f in os.listdir(UPLOADS_DIR)
            if os.path.isfile(os.path.join(UPLOADS_DIR, f))
        ]
        if len(files) > max_keep:
            files.sort(key=os.path.getmtime)
            for old in files[: len(files) - max_keep]:
                try:
                    os.remove(old)
                except OSError:
                    pass
    except OSError:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize SQLite DB, index dataset images, and load WasteClassifier on startup."""
    global classifier, simulation_running, simulation_task, dataset_samples

    init_db()
    dataset_samples = _scan_dataset_images()
    total_imgs = sum(len(v) for v in dataset_samples.values())
    if total_imgs > 0:
        print(f"Indexed {total_imgs} dataset images across {len(dataset_samples)} classes.")

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

# Mount dataset directory at /dataset so real TrashNet images can be rendered in 3D
if os.path.isdir(DATASET_DIR):
    app.mount("/dataset", StaticFiles(directory=DATASET_DIR), name="dataset")

# Mount uploaded images directory at /uploads
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")


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
        return FileResponse(
            INDEX_HTML_PATH,
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )
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

    suffix = os.path.splitext(file.filename or "upload.jpg")[1].lower() or ".jpg"
    if suffix not in IMAGE_EXTENSIONS:
        suffix = ".jpg"
    unique_name = f"{uuid.uuid4().hex}{suffix}"
    saved_path = os.path.join(UPLOADS_DIR, unique_name)
    image_url = f"/uploads/{unique_name}"

    try:
        with open(saved_path, "wb") as out_f:
            shutil.copyfileobj(file.file, out_f)
        _cleanup_old_uploads(max_keep=25)

        result = await asyncio.to_thread(classifier.predict, saved_path)
        detected_class = result["class"]
        confidence = result["confidence"]

        event_id = await asyncio.to_thread(
            add_sort_event,
            detected_class,
            confidence,
            detected_class,
            True,
            image_url,
        )

        event_payload = {
            "id": event_id,
            "detected_class": detected_class,
            "confidence": confidence,
            "assigned_bin": detected_class,
            "success": True,
            "image_url": image_url,
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
                "image_url": image_url,
                **result,
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        if os.path.exists(saved_path):
            try:
                os.remove(saved_path)
            except OSError:
                pass
        raise HTTPException(status_code=500, detail=f"Prediction failed: {e}")


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
    """Background asyncio task feeding real TrashNet images through MobileNetV2 (with random fallback)."""
    global simulation_running
    try:
        while simulation_running:
            waste_class = random.choices(WASTE_CLASSES, weights=WASTE_WEIGHTS, k=1)[0]
            image_url = None

            if classifier is not None and dataset_samples.get(waste_class):
                # Feed a real TrashNet image through the trained MobileNetV2 model
                abs_path, image_url = random.choice(dataset_samples[waste_class])
                result = await asyncio.to_thread(classifier.predict, abs_path)
                detected = result["class"]
                confidence = result["confidence"]
                success = detected == waste_class
            else:
                # Fallback simulated classification (~92% accuracy)
                confidence = round(random.uniform(0.70, 0.99), 4)
                if random.random() > 0.92:
                    wrong_classes = [c for c in WASTE_CLASSES if c != waste_class]
                    detected = random.choice(wrong_classes)
                    confidence = round(random.uniform(0.40, 0.75), 4)
                else:
                    detected = waste_class
                success = detected == waste_class

            # Record in database
            event_id = await asyncio.to_thread(
                add_sort_event, detected, confidence, detected, success, image_url
            )

            # Broadcast to all connected WebSocket clients
            await manager.broadcast(
                {
                    "type": "sort_event",
                    "data": {
                        "id": event_id,
                        "detected_class": detected,
                        "true_class": waste_class,
                        "confidence": confidence,
                        "assigned_bin": detected,
                        "success": success,
                        "image_url": image_url,
                        "timestamp": datetime.datetime.now().isoformat(),
                    },
                }
            )

            # Also broadcast updated stats and bin status
            await manager.broadcast(
                {"type": "stats_update", "data": await asyncio.to_thread(get_statistics)}
            )
            await manager.broadcast(
                {"type": "bins_update", "data": await asyncio.to_thread(get_bin_statuses)}
            )

            await asyncio.sleep(random.uniform(2.2, 3.4))
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
