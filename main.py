import json
import os
import shutil
import uuid
from pathlib import Path

import psutil
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               RedirectResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
import aiofiles

from settings import STORAGE_PATH, SECRET_KEY
from database import init_db, authenticate

# ─── App setup ───────────────────────────────────────────────────────────────

app = FastAPI(title="My Local Cloud")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, max_age=86400)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

init_db()

# ─── Extensions store ────────────────────────────────────────────────────────

EXTENSIONS_FILE = Path(STORAGE_PATH) / "extensions.json"

DEFAULT_EXTENSIONS: list[dict] = [
    {
        "id": "drive",
        "name": "Файлы",
        "emoji": "📁",
        "url": "/drive",
        "color": "#0A84FF",
        "builtin": True,
    }
]


def load_extensions() -> list[dict]:
    if EXTENSIONS_FILE.exists():
        try:
            return json.loads(EXTENSIONS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return DEFAULT_EXTENSIONS.copy()


def save_extensions(exts: list[dict]) -> None:
    EXTENSIONS_FILE.write_text(
        json.dumps(exts, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ─── Auth helpers ─────────────────────────────────────────────────────────────

def get_current_user(request: Request) -> str | None:
    return request.session.get("username")


def require_login(request: Request) -> str:
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    return user


# ─── File-system helpers ──────────────────────────────────────────────────────

def get_user_base(username: str) -> Path:
    base = Path(STORAGE_PATH) / username
    base.mkdir(parents=True, exist_ok=True)
    return base


def resolve_safe(base: Path, rel: str) -> Path:
    target = (base / rel).resolve()
    base_r = base.resolve()
    if target != base_r and not str(target).startswith(str(base_r) + os.sep):
        raise HTTPException(status_code=400, detail="Недопустимый путь")
    return target


def human_readable_size(size_bytes: int) -> str:
    for unit in ["Б", "КБ", "МБ", "ГБ"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes //= 1024
    return f"{size_bytes:.1f} ТБ"


def list_directory(dir_path: Path):
    folders, files = [], []
    for entry in os.scandir(dir_path):
        if entry.is_dir():
            folders.append({"name": entry.name})
        elif entry.is_file():
            size = entry.stat().st_size
            files.append({"name": entry.name, "size": size,
                          "size_human": human_readable_size(size)})
    folders.sort(key=lambda f: f["name"].lower())
    files.sort(key=lambda f: f["name"].lower())
    return folders, files


def build_breadcrumbs(path: str) -> list[dict]:
    if not path:
        return []
    parts = Path(path).parts
    return [{"name": p, "path": str(Path(*parts[: i + 1]))}
            for i, p in enumerate(parts)]


def parent_path(path: str) -> str:
    p = str(Path(path).parent)
    return "" if p == "." else p


# ═══════════════════════════════════════════════════════════════════════════════
# HUB  (public)
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def hub(request: Request):
    return templates.TemplateResponse(request, "hub.html", {"request": request})


@app.get("/api/stats")
async def system_stats():
    cpu = psutil.cpu_percent(interval=0.1)
    mem = psutil.virtual_memory()
    try:
        disk = psutil.disk_usage(Path.cwd().anchor)
        disk_info = {
            "used": round(disk.used / 1_073_741_824, 1),
            "total": round(disk.total / 1_073_741_824, 1),
            "percent": round(disk.percent, 1),
        }
    except Exception:
        disk_info = {"used": 0, "total": 0, "percent": 0}

    return {
        "cpu": round(cpu, 1),
        "memory": {
            "used": round(mem.used / 1_073_741_824, 1),
            "total": round(mem.total / 1_073_741_824, 1),
            "percent": round(mem.percent, 1),
        },
        "disk": disk_info,
    }


@app.get("/api/extensions")
async def get_extensions():
    return load_extensions()


@app.post("/api/extensions")
async def add_extension(request: Request):
    data = await request.json()
    exts = load_extensions()
    new = {
        "id": uuid.uuid4().hex[:8],
        "name": str(data.get("name", "App"))[:32],
        "emoji": str(data.get("emoji", "🔗"))[:4],
        "url": str(data.get("url", "#")),
        "color": str(data.get("color", "#5856D6")),
        "builtin": False,
    }
    exts.append(new)
    save_extensions(exts)
    return new


@app.delete("/api/extensions/{ext_id}")
async def delete_extension(ext_id: str):
    exts = load_extensions()
    exts = [e for e in exts if e["id"] != ext_id or e.get("builtin")]
    save_extensions(exts)
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════════════════
# AUTH
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if get_current_user(request):
        return RedirectResponse(url="/drive", status_code=302)
    return templates.TemplateResponse(
        request, "login.html", {"request": request, "error": None}
    )


@app.post("/login", response_class=HTMLResponse)
async def login(request: Request,
                username: str = Form(...),
                password: str = Form(...)):
    if authenticate(username, password):
        request.session["username"] = username
        return RedirectResponse(url="/drive", status_code=302)
    return templates.TemplateResponse(
        request, "login.html",
        {"request": request, "error": "Неверный логин или пароль"}
    )


@app.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=302)


# ═══════════════════════════════════════════════════════════════════════════════
# DRIVE
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/drive", response_class=HTMLResponse)
async def drive_index(request: Request, path: str = ""):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    base = get_user_base(user)
    current_dir = resolve_safe(base, path)
    if not current_dir.is_dir():
        return RedirectResponse(url="/drive", status_code=302)

    folders, files = list_directory(current_dir)
    breadcrumbs = build_breadcrumbs(path)
    up = parent_path(path) if path else None

    return templates.TemplateResponse(request, "index.html", {
        "request": request,
        "username": user,
        "files": files,
        "folders": folders,
        "current_path": path,
        "breadcrumbs": breadcrumbs,
        "up_path": up,
    })


@app.post("/upload")
async def upload_file(request: Request,
                      file: UploadFile = File(...),
                      path: str = Form("")):
    user = require_login(request)
    if not file.filename:
        raise HTTPException(status_code=400, detail="Имя файла обязательно")
    base = get_user_base(user)
    current_dir = resolve_safe(base, path)
    async with aiofiles.open(current_dir / Path(file.filename).name, "wb") as f:
        await f.write(await file.read())
    return RedirectResponse(
        url=f"/drive?path={path}" if path else "/drive", status_code=302
    )


@app.get("/download/{rel_path:path}")
async def download_file(rel_path: str, request: Request):
    user = require_login(request)
    base = get_user_base(user)
    full_path = resolve_safe(base, rel_path)
    if not full_path.is_file():
        raise HTTPException(status_code=404, detail="Файл не найден")
    return FileResponse(full_path, filename=full_path.name,
                        media_type="application/octet-stream")


@app.post("/delete/{rel_path:path}")
async def delete_file(rel_path: str, request: Request):
    user = require_login(request)
    base = get_user_base(user)
    full_path = resolve_safe(base, rel_path)
    if not full_path.is_file():
        raise HTTPException(status_code=404, detail="Файл не найден")
    os.unlink(full_path)
    back = parent_path(rel_path)
    return RedirectResponse(
        url=f"/drive?path={back}" if back else "/drive", status_code=302
    )


@app.post("/mkdir")
async def make_directory(request: Request,
                         name: str = Form(...),
                         path: str = Form("")):
    user = require_login(request)
    if not name or any(c in name for c in r'/\:*?"<>|') or name in (".", ".."):
        raise HTTPException(status_code=400, detail="Недопустимое имя папки")
    base = get_user_base(user)
    current_dir = resolve_safe(base, path)
    (current_dir / name).mkdir(exist_ok=True)
    return RedirectResponse(
        url=f"/drive?path={path}" if path else "/drive", status_code=302
    )


@app.post("/deletefolder/{rel_path:path}")
async def delete_folder(rel_path: str, request: Request):
    user = require_login(request)
    base = get_user_base(user)
    full_path = resolve_safe(base, rel_path)
    if not full_path.is_dir():
        raise HTTPException(status_code=404, detail="Папка не найдена")
    shutil.rmtree(full_path)
    back = parent_path(rel_path)
    return RedirectResponse(
        url=f"/drive?path={back}" if back else "/drive", status_code=302
    )


@app.post("/move")
async def move_file(request: Request):
    user = require_login(request)
    data = await request.json()
    src_rel = data.get("src", "")
    dst_rel = data.get("dst", "")
    if not src_rel:
        raise HTTPException(status_code=400, detail="Не указан источник")
    base = get_user_base(user)
    src_path = resolve_safe(base, src_rel)
    dst_path = resolve_safe(base, dst_rel) if dst_rel else base
    if not src_path.is_file():
        raise HTTPException(status_code=404, detail="Файл не найден")
    if not dst_path.is_dir():
        raise HTTPException(status_code=400, detail="Целевая папка не найдена")
    target = dst_path / src_path.name
    if target != src_path:
        src_path.rename(target)
    return JSONResponse({"ok": True})