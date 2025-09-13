from fastapi import FastAPI

app = FastAPI(title="Reelay API")

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.get("/hello")
def hello(name: str = "world"):
    return {"message": f"hello {name}"}

# Run: uvicorn main:app --reload --port 8000
