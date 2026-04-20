from fastapi import FastAPI

app = FastAPI(title="WhatsApp Inbox")


@app.get("/")
def read_root():
    return {"status": "ok"}