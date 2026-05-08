class StatusButton extends HTMLButtonElement {
    constructor() {
        super();
        this.textContent = 'Status';
        this.addEventListener('click', async () => {
            const statusResultElement = document.getElementById('status-result');
            const result = await getStatus();
            statusResultElement.textContent = `Status: ${result}`;
        });
    }
}

customElements.define('status-button', StatusButton, { extends: 'button' });