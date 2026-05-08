// Función para realizar el request a /ping
async function pingRequest() {
    try {
        const response = await fetch('/ping');
        const jsonResponse = await response.json();
        
        // Comparamos la respuesta con {"message": "pong"}
        if (jsonResponse.message === 'pong') {
            console.log('La respuesta es correcta');
        } else {
            console.error('La respuesta no coincide con {"message": "pong"}');
        }
    } catch (error) {
        console.error('Error al realizar el request:', error);
    }
}

// Llamamos a la función para realizar el request
pingRequest();