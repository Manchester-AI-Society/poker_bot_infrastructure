from dotenv import load_dotenv

from server.api.fastapi_application import app  # noqa: F401 (uvicorn target)

load_dotenv()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "server.run_poker_server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
