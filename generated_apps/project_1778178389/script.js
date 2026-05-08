// Seleccionar elementos del DOM
const pingBtn = document.getElementById('ping-btn');
const pingResponse = document.getElementById('ping-response');
const timeBtn = document.getElementById('time-btn');
const timeResponse = document.getElementById('time-response');
const statusBtn = document.getElementById('status-btn');
const statusResponse = document.getElementById('status-response');

// Agregar eventos a los botones
pingBtn.addEventListener('click', async () => {
    try {
        const response = await fetch('/ping');
        const data = await response.json();
        pingResponse.innerText = `Ping: ${data.ping}`;
    } catch (error) {
        console.error(error);
        pingResponse.innerText = 'Error al enviar ping';
    }
});

timeBtn.addEventListener('click', async () => {
    try {
        const response = await fetch('/time');
        const data = await response.json();
        timeResponse.innerText = `Tiempo: ${data.time}`;
    } catch (error) {
        console.error(error);
        timeResponse.innerText = 'Error al obtener tiempo';
    }
});

statusBtn.addEventListener('click', async () => {
    try {
        const response = await fetch('/status');
        const data = await response.json();
        statusResponse.innerText = `Estado del sistema: ${data.status}`;
    } catch (error) {
        console.error(error);
        statusResponse.innerText = 'Error al obtener estado del sistema';
    }
});