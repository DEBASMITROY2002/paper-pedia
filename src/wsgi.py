"""ASGI entry point: uvicorn wsgi:app --app-dir src --reload."""
from paper_pedia.server.app import app
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("wsgi:app", host="127.0.0.1", port=8000, reload=True)
