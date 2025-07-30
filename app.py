import os
from dotenv import load_dotenv
import uvicorn

load_dotenv()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))  # fallback to 8000 if missing
    ip = os.getenv("IP", "0.0.0.0")
    uvicorn.run("server:app", host=ip, port=port, reload=True)
