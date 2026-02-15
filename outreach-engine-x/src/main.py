import modal
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = modal.App("outbound-engine-x")

image = modal.Image.debian_slim(python_version="3.11").pip_install(
    "fastapi>=0.115.0",
    "uvicorn>=0.30.0",
)

web_app = FastAPI(title="Outbound Engine X", version="0.1.0")

web_app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3003"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@web_app.get("/")
async def root():
    return {"status": "ok", "service": "outbound-engine-x"}


@web_app.get("/health")
async def health():
    return {"status": "healthy"}


@app.function(image=image)
@modal.asgi_app()
def fastapi_app():
    return web_app