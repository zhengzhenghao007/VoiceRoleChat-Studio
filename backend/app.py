from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.characters import router as characters_router
from api.transcriptions import router as transcriptions_router
from api.voices import router as voices_router
from config import create_project_directories


create_project_directories()

app = FastAPI(
    title="VoiceRoleChat Studio API",
    version="0.6.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(characters_router)
app.include_router(voices_router)
app.include_router(transcriptions_router)


@app.get("/", tags=["System"])
def read_root():
    return {
        "message": "VoiceRoleChat Studio backend is running"
    }


@app.get("/health", tags=["System"])
def health_check():
    return {
        "status": "healthy"
    }