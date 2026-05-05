import os
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Request, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import aiofiles

from settings import STORAGE_PATH

app = FastAPI(title="My Local Cloud")

templates = Jinja2Templates(directory="templates")

def get_file_list():
    files = []
    for entry in os.scandir(STORAGE_PATH):
        if entry.is_file():
            files.append({
                "name": entry.name,
                "size": entry.stat().st_size
            })
    files.sort(key=lambda f: f["name"].lower())
    return files

def human_readable_size(size_bytes: int) -> str:
    for unit in ["Б", "КБ", "МБ", "ГБ"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} ТБ"

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    files = get_file_list()
    for f in files:
        f["size_human"] = human_readable_size(f["size"])
    return templates.TemplateResponse(
        request,
        name="index.html",
        context={"request": request, "files": files}
    )

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Имя файла обязательно")
    safe_name = Path(file.filename).name
    file_path = os.path.join(STORAGE_PATH, safe_name)
    async with aiofiles.open(file_path, "wb") as out_file:
        content = await file.read()
        await out_file.write(content)
    return RedirectResponse(url="/", status_code=302)

@app.get("/download/{file_name}")
async def download_file(file_name: str):
    file_path = os.path.join(STORAGE_PATH, file_name)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Файл не найден")
    return FileResponse(file_path, filename=file_name, media_type="application/octet-stream")

@app.post("/delete/{file_name}")
async def delete_file(file_name: str):
    file_path = os.path.join(STORAGE_PATH, file_name)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Файл не найден")
    os.unlink(file_path)
    return RedirectResponse(url="/", status_code=302)