export class Messages {
    root;

    constructor(root) {
        this.root = root;
        for (const el of root.querySelectorAll('ul.messages li')) {
            el.prepend(<a href="#" className="close" onClick={e => this.close(e, el)}>
                <i className="material-icons">close</i>
            </a>)
        }

    }

    close = (e, el) => {
        e.preventDefault();
        el.remove();
    }
}