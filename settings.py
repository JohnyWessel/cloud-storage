import os

STORAGE_PATH: str = os.environ.get("STORAGE_PATH", "./storage")
DB_PATH: str      = os.environ.get("DB_PATH",      "./storage/cloud.db")
SECRET_KEY: str   = os.environ.get("SECRET_KEY",   "change-me-in-production-please")

os.makedirs(STORAGE_PATH, exist_ok=True)
