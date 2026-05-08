class Button extends HTMLElement {
    constructor() {
        super();
        this.text = this.getAttribute('text');
        this.render();
    }

    render() {
        this.innerHTML = `
            <button>${this.text}</button>
        `;
    }
}

export { Button };