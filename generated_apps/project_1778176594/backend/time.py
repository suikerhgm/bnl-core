from datetime import datetime
from fastapi import Response

def time():
    return {"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}