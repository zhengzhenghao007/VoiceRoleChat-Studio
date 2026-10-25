from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.characters import router as characters_router
from api.datasets import router as datasets_router
from api.models import router as models_router
from api.llm import router as llm_router
from api.training import router as training_router, start_training_queue, close_training_queue
from api.transcriptions import router as transcriptions_router, close_jobs
from api.voices import router as voices_router
from api.tts import router as tts_router, close_tts_service
from config import create_project_directories, PROJECT_ROOT
from services.segmented_dataset_service import cleanup_retained
from services.training_command import start_training_commands,close_training_commands


create_project_directories()


@asynccontextmanager
async def lifespan(app):
    start_training_commands()
    start_training_queue()
    try:
        yield
    finally:
        try:
            await run_in_threadpool(close_training_queue)
        finally:
            try:
                await run_in_threadpool(close_training_commands)
            finally:
                try:
                    await run_in_threadpool(close_jobs)
                finally:
                    try:
                        await run_in_threadpool(cleanup_retained)
                    finally:
                        await run_in_threadpool(close_tts_service)


app = FastAPI(
    title="VoiceRoleChat Studio API",
    version="0.9.0",
    lifespan=lifespan,
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
app.include_router(training_router)
app.include_router(datasets_router)
app.include_router(models_router)
app.include_router(tts_router)
app.include_router(llm_router)
app.mount("/studio", StaticFiles(directory=PROJECT_ROOT / "frontend", html=True), name="studio")


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
