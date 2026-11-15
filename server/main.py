from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .auth.route import router as auth_router, ensure_admin
from .reports.route import router as report_router
from .diagnosis.route import router as diagnosis_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_admin()  # unique usernames + bootstrap the first admin from .env
    yield


app = FastAPI(title="RBAC Medical Report Diagnosis", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(report_router)
app.include_router(diagnosis_router)


@app.get("/health", tags=["health"])
def health_check():
    return {"status": "healthy"}
