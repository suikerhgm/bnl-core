from fastapi import Response

def ping():
    return {"ping": "pong"}