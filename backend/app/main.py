from fastapi import FastAPI

app = FastAPI(title="AI Study App API")

@app.get("/")
def root():
    return {"message": "AI Study App backend is running"}
