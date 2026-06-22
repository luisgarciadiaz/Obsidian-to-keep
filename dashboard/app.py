import logging
from pathlib import Path
from typing import Optional

try:
    import uvicorn
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse, JSONResponse
    from fastapi.templating import Jinja2Templates
except ImportError:
    FastAPI = None
    HTMLResponse = None
    JSONResponse = None

from sync.engine import SyncEngine
from sync.state import SyncStateDB

log = logging.getLogger(__name__)

app = FastAPI(title="Obsidian ↔ Keep Sync Dashboard")

engine_ref: Optional[SyncEngine] = None
state_ref: Optional[SyncStateDB] = None

templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir)) if FastAPI else None


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    if not engine_ref:
        return HTMLResponse("Engine not initialized", status_code=500)
    stats = engine_ref.stats
    all_notes = state_ref.all() if state_ref else []
    conflicts = state_ref.conflicts() if state_ref else []

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "stats": stats,
            "total_notes": len(all_notes),
            "conflicts": len(conflicts),
            "conflict_list": conflicts[:20],
        },
    )


@app.get("/api/notes")
async def api_notes():
    if not state_ref:
        return JSONResponse({"error": "Not initialized"}, status_code=500)
    notes = state_ref.all()
    return JSONResponse(
        [
            {
                "note_id": n.note_id,
                "file_path": n.file_path,
                "conflict": n.conflict,
                "sync_direction": n.sync_direction,
                "obsidian_mtime": n.obsidian_mtime,
                "keep_updated": n.keep_updated,
            }
            for n in notes
        ]
    )


@app.get("/api/stats")
async def api_stats():
    if not engine_ref:
        return JSONResponse({"error": "Not initialized"}, status_code=500)
    return JSONResponse(engine_ref.stats)


@app.post("/api/sync")
async def api_sync():
    if not engine_ref:
        return JSONResponse({"error": "Not initialized"}, status_code=500)
    try:
        push, pull = engine_ref.run_once()
        return JSONResponse({"status": "ok", "pushed": len(push), "pulled": len(pull)})
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@app.get("/api/logs")
async def api_logs(lines: int = 50):
    log_path = Path("sync.log")
    if not log_path.exists():
        return JSONResponse({"logs": []})
    content = log_path.read_text().splitlines()
    return JSONResponse({"logs": content[-lines:]})


@app.get("/api/conflicts")
async def api_conflicts():
    if not state_ref:
        return JSONResponse({"error": "Not initialized"}, status_code=500)
    conflicts = state_ref.conflicts()
    return JSONResponse(
        [
            {
                "note_id": c.note_id,
                "file_path": c.file_path,
                "obsidian_mtime": c.obsidian_mtime,
                "keep_updated": c.keep_updated,
            }
            for c in conflicts
        ]
    )


def run_dashboard(
    engine: SyncEngine,
    state_db: SyncStateDB,
    host: str = "127.0.0.1",
    port: int = 8765,
):
    global engine_ref, state_ref
    engine_ref = engine
    state_ref = state_db

    log.info("Starting dashboard at http://%s:%d", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")
