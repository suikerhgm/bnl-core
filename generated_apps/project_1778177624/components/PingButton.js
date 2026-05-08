class PingButton extends HTMLButtonElement {
    constructor() {
        super();
        this.textContent = 'Ping';
        this.addEventListener('click', async () => {
            const pingResultElement = document.getElementById('ping-result');
            const result = await pingServer();
            pingResultElement.textContent = `Ping: ${result}`;
        });
    }
}

customElements.define('ping-button', PingButton, { extends: 'button' });