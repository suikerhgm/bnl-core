class Time extends HTMLElement {
    constructor() {
        super();
        this.render();
    }

    render() {
        this.innerHTML = `
            <p>Time: <span id="time">00:00:00</span></p>
        `;
        // Actualización del tiempo cada segundo
        setInterval(() => {
            const now = new Date();
            const hours = now.getHours().toString().padStart(2, '0');
            const minutes = now.getMinutes().toString().padStart(2, '0');
            const seconds = now.getSeconds().toString().padStart(2, '0');
            this.querySelector('#time').innerText = `${hours}:${minutes}:${seconds}`;
        }, 1000);
    }
}

export { Time };