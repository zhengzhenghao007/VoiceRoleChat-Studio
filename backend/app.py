from fastapi import FastAPI

app = FastAPI(
    title="VoiceRoleChat Studio API",
    version="0.1.0",
)


@app.get("/")
def read_root():
    return {
        "message": "VoiceRoleChat Studio backend is running"
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy"
    }