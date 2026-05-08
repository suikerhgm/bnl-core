class TimeButton extends HTMLButtonElement {
    constructor() {
        super();
        this.textContent = 'Time';
        this.addEventListener('click', async () => {
            const timeResultElement = document.getElementById('time-result');
            const result = await getTime();
            timeResultElement.textContent = `Time: ${result}`;
        });
    }
}

customElements.define('time-button', TimeButton, { extends: 'button' });