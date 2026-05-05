import os

STORAGE_PATH = os.environ.get("STORAGE_PATH", "./storage")

os.makedirs(STORAGE_PATH, exist_ok=True)