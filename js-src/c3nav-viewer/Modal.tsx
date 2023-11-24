export class Modal {
    root;
    content;

    noclose = false;

    constructor(root) {
        this.root = root;
        this.content = root.querySelector('#modal-content');
        on(root, 'click', this.onClick);
        on(root, 'click', 'a', this.onLinkClick);
        on(root, 'submit', 'form', this.onSubmit);
        on(root, 'click', '.mobileclient-share', this.onMobileclientShareClick);
        on(root, 'click', '.mobileclient-shortcut', this.onMobileclientShortcutClick);
    }

    onClick = e => {
        if (!this.noclose && (e.target.id === 'modal' || e.target.id === 'close-modal')) {
            history.back();
        }
    }

    open = (content, no_close) => {
        this.noclose = no_close;
        this.setContent(content, no_close);
        if (!this.root.classList.contains('show')) {
            c3nav._push_state({modal: true, sidebar: true});
            this.root.classList.add('show');
        }
    }

    hide = () => {
        this.root.classList.remove('show');
    }

    onLinkClick = async (e, el) => {
        const location = el.href;
        if (el.target || location.startsWith('/control/')) {
            el.target = '_blank';
            return;
        }
        e.preventDefault();
        e.stopPropagation();
        c3nav.modal.open();
        await this.load(fetch(location));
    }

    load = async (fetch_promise) => {
        try {
            const res = await fetch_promise;
            if (res.ok) {
                const contentType = res.headers.get('content-type');
                if (contentType && contentType.includes('application/json')) {
                    const data = await res.json();
                    c3nav._set_user_data(data);
                    history.back(); // close the modal if the response was data-only
                } else {
                    const html = await res.text();
                    const doc = (new DOMParser()).parseFromString(html, 'text/html');
                    const data = (doc.querySelector('[data-user-data]') as HTMLElement)?.dataset?.userData ?? null;
                    if (data) {
                        c3nav._set_user_data(JSON.parse(data));
                    }
                    this.setContent(doc.querySelector('main').cloneNode(true).childNodes);
                }
            } else {
                this.setError(res.statusText);
            }
        } catch (e) {
            this.setError(e.message);
        }
    }

    setError = message => {
        this.content.replaceChildren(<h3>Error {message}</h3>);
        this.setLoading(false);
    }

    setContent = (content, no_close = false) => {
        this.content.replaceChildren();
        if (!no_close) {
            this.content.append(<button className="button-clear material-icons" id="close-modal">clear</button>);
        }
        if (content) {
            if (content instanceof NodeList || content instanceof HTMLCollection || Array.isArray(content)) {
                this.content.append(...content);
            } else {
                this.content.append(content);
            }
        }
        this.setLoading(!content);
    }

    setLoading = loading => {
        this.root.classList.toggle('loading', loading);
    }


    onSubmit = async (e, el) => {
        e.preventDefault();
        await this.load(fetch(el.action, {
            method: 'POST',
            body: new FormData(el),
        }));
    }

    onMobileclientShareClick = (e, el) => {
        mobileclient.shareUrl(this.root.querySelector('.share-ui input').value);
    }

    onMobileclientShortcutClick = (e, el) => {
        mobileclient.createShortcut(this.root.querySelector('.share-ui input').value, c3nav.state.destination.title);
    }

}