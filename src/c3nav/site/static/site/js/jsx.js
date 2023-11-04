(function () {
    const jsx_fragment = Symbol('jsx_fragment');

    function append_children(element, children) {
        for (const child of children) {
            if (child instanceof HTMLElement || child instanceof DocumentFragment) {
                element.append(child);
            } else if (Array.isArray(child)) {
                append_children(element, child);
            } else if (child) {
                element.append('' + child);
            }
        }
    }

    function jsx_create(tag, attributes, ...children) {
        if (typeof tag === 'function') {
            return tag({...attributes, children: children});
        }
        let element;
        if (typeof tag === 'string') {
            element = document.createElement(tag);
        } else if (tag === jsx_fragment) {
            element = new DocumentFragment();
        } else {
            throw new Error('jsx tag type must be a string, a function or the fragment symbol');
        }
        if (tag !== jsx_fragment && attributes != null) {
            for (const key of Object.keys(attributes)) {
                if (typeof attributes[key] === 'function') {
                    // event handler
                    let event_name;
                    if (key.startsWith('on')) {
                        event_name = key.substring(2).toLowerCase();
                    } else {
                        event_name = key;
                    }
                    element.addEventListener(event_name, attributes[key]);
                } else if (key.startsWith('data-')) {
                    const name = key.substring(5)
                        .toLowerCase()
                        .replace(/(-[a-z])/g, x => x.toUpperCase().replace('-', ''));
                    element.dataset[name] = attributes[key];
                } else {
                    element[key] = attributes[key];
                }

            }
        }
        append_children(element, children);
        return element;
    }

    window.jsx_fragment = jsx_fragment;
    window.jsx_create = jsx_create;
})();