from fastapi import FastAPI
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    raise Exception("Test crash")
    yield

app = FastAPI(lifespan=lifespan)
