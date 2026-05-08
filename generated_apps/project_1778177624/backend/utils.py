import datetime
import platform
import psutil

def ping():
    """Realiza un ping al servidor y devuelve una respuesta"""
    response = {"message": "Pong"}
    return response

def get_time():
    """Obtiene la hora actual del servidor y devuelve una respuesta"""
    time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    response = {"time": time}
    return response

def get_status():
    """Obtiene el estado del servidor y devuelve una respuesta"""
    status = {
        "cpu": psutil.cpu_percent(),
        "memory": psutil.virtual_memory().percent,
        "os": platform.system(),
        "version": platform.release()
    }
    response = {"status": status}
    return response