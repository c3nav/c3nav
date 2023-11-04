(function () {
    const jsx_fragment = Symbol('jsx_fragment');

    function append_children(element, children) {
        for (const child of children) {
            if (child instanceof HTMLElement || child instanceof DocumentFragment) {
                element.append(child);
            } else if (Array.isArray(child)) {
                append_children(element, child);
            } else if (child) {
                element.append(''+child);
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
        if (attributes != null) {
            for (const key of Object.keys(attributes)) {
                element.setAttribute(key, attributes[key]);
            }
        }
        append_children(element, children);
        return element;
    }
    window.jsx_fragment = jsx_fragment;
    window.jsx_create = jsx_create;
})();