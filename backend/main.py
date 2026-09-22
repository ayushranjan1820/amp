from fastapi import FastAPI
import uvicorn
from routes.user_route import router as user_router
from routes.agent_route import router as agent_router
from utils.logger import get_logger

logger = get_logger("main")

app = FastAPI(title="Agent Mart API")

# Register user router (router lifespan manages UserProfileCollection lifecycle)
app.include_router(user_router, prefix="/api/v1/users")
app.include_router(agent_router, prefix="/api/v1/agents")
logger.info("User router registered at prefix /api/v1/users")


@app.get("/")
async def root():
    logger.info("Root endpoint GET / requested.")
    return {"message": "Agent Mart API is running"}


if __name__ == "__main__":
    logger.info("Starting Uvicorn server at http://0.0.0.0:8000...")
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
