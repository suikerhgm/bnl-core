// Obtener elementos del DOM
const pingResult = document.getElementById('ping-result');
const timeResult = document.getElementById('time-result');
const statusResult = document.getElementById('status-result');

// Función para obtener el estado del servidor
async function getStatus() {
    try {
        const response = await fetch('/status');
        const data = await response.json();
        return data.status;
    } catch (error) {
        console.error(error);
        return 'Error al obtener el estado del servidor';
    }
}

// Función para obtener el tiempo del servidor
async function getTime() {
    try {
        const response = await fetch('/time');
        const data = await response.json();
        return data.time;
    } catch (error) {
        console.error(error);
        return 'Error al obtener el tiempo del servidor';
    }
}

// Función para realizar un ping al servidor
async function pingServer() {
    try {
        const response = await fetch('/ping');
        const data = await response.json();
        return data.ping;
    } catch (error) {
        console.error(error);
        return 'Error al realizar el ping al servidor';
    }
}