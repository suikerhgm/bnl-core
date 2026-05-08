// Cargar navegación y botones
fetch('navegacion.html')
    .then(response => response.text())
    .then(html => {
        const navegacion = document.getElementById('navegacion');
        navegacion.innerHTML = html;
    });

fetch('botones.html')
    .then(response => response.text())
    .then(html => {
        const botones = document.getElementById('botones');
        botones.innerHTML = html;
    });

// Simular obtener estado del sistema
setInterval(() => {
    fetch('/api/estado')
        .then(response => response.json())
        .then(data => {
            const ping = document.getElementById('ping');
            const time = document.getElementById('time');
            const status = document.getElementById('status');

            ping.textContent = `Ping: ${data.ping} ms`;
            time.textContent = `Tiempo: ${data.time}`;
            status.textContent = `Estado: ${data.status}`;
        })
        .catch(error => console.error('Error al obtener estado del sistema:', error));
}, 1000);