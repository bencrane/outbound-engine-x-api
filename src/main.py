from fastapi import FastAPI

app = FastAPI(title="Outbound Engine X", version="0.1.0")


@app.get("/")
async def root():
    return {"status": "ok", "service": "outbound-engine-x"}


@app.get("/health")
async def health():
    return {"status": "healthy"}
