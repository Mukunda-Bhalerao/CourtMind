from langchain_ollama import OllamaLLM
import os
from fastapi import FastAPI, Body
from fastapi.responses import StreamingResponse, JSONResponse
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize FastAPI app
app = FastAPI(
    title="CourtMind",
    description="AI-powered legal analysis system",
    version="2.0.0",
)

# Initialize Ollama LLM
ollama_model = os.getenv("OLLAMA_MODEL", "gpt-oss:120b-cloud")
base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

print("="*80)
print("CourtMind - LLM INITIALIZATION")
print("="*80)
print(f"Model: {ollama_model}")
print(f"Base URL: {base_url}")
print("="*80)

try:
    llm = OllamaLLM(model=ollama_model, stop=["\nObservation:"])
    llm.invoke("test")
    print("LLM initialized and connected to Ollama successfully")
except Exception as e:
    print(f"ERROR: Failed to initialize or connect to Ollama: {e}")
    print("Please ensure Ollama is running and the model is pulled")
    raise

print("="*80)


@app.get("/health")
async def health_check():
    return JSONResponse({"status": "ok", "model": ollama_model})


# TODO: New CourtMind endpoints will be added here


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)