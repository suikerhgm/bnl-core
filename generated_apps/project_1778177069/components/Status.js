class Status extends HTMLElement {
    constructor() {
        super();
        this.render();
    }

    render() {
        this.innerHTML = `
            <p>Status: <span id="status">Unknown</span></p>
        `;
        // Simulación de llamada a API para obtener status
        setTimeout(() => {
            this.querySelector('#status').innerText = 'OK';
        }, 1000);
    }
}

export { Status };