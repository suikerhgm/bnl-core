import psutil
import datetime
import platform
import os

def get_system_info():
    info = {}
    info["system"] = platform.system()
    info["release"] = platform.release()
    info["version"] = platform.version()
    info["processor"] = platform.processor()
    return info

def get_system_status():
    status = {}
    status["cpu_percent"] = psutil.cpu_percent()
    status["memory_percent"] = psutil.virtual_memory().percent
    status["disk_percent"] = psutil.disk_usage('/').percent
    return status

def get_current_time():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def ping_host(host):
    response = os.system("ping -c 1 " + host)
    if response == 0:
        return True
    else:
        return False