type EventHandler = (e: Event, el: Node) => void;


const event_handlers = new WeakMap();

const event_handler = (root_node) => {
    return (e) => {
        const handler_map = event_handlers.get(root_node);
        if (!handler_map || !handler_map[e.type]) {
            console.warn('event handler called but no events registers, this is probably a bug in the event handling system');
            return;
        }
        const handlers = handler_map[e.type];

        let current = e.target;
        while (true) {
            for (const {selector, handler} of handlers.sub_handlers) {
                if ((selector === null && current === root_node)
                    || (selector !== null && typeof current.matches === 'function' && current.matches(selector))) {
                    handler(e, current);
                }
            }
            if (current === root_node) {
                break;
            } else {
                current = current.parentNode;
            }
            if (current === null) {
                break;
            }
        }
    }
}


function get_nodes(selector) {
    if (typeof selector === 'string') {
        return document.querySelectorAll(selector);
    } else if (selector instanceof Node) {
        return [selector];
    } else if (selector instanceof NodeList
        || selector instanceof HTMLCollection
        || (Array.isArray(selector) && selector.every(e => e instanceof Node))) {
        return selector;
    } else {
        throw new Error('selector must be string/Node/Node[]/NodeList/HTMLCollection')
    }
}

export function on(selector, type, subselector, handler: EventHandler) {
    const nodes = get_nodes(selector);

    if (typeof handler === 'undefined') {
        handler = subselector
        subselector = null;
    }

    for (const node of nodes) {
        let event_map;
        if (event_handlers.has(node)) {
            event_map = event_handlers.get(node);
        } else {
            event_map = {};
            event_handlers.set(node, event_map);
        }
        if (event_map.hasOwnProperty(type)) {
            event_map[type].sub_handlers.push({
                selector: subselector,
                handler: handler,
            });
        } else {
            event_map[type] = {
                handler: event_handler(node),
                sub_handlers: [{
                    selector: subselector,
                    handler: handler,
                }]
            };
            node.addEventListener(type, event_map[type].handler);
        }
    }
}

export function off(selector, type, subselector, handler: EventHandler) {
    const nodes = get_nodes(selector);

    if (typeof handler === 'undefined') {
        handler = subselector
        subselector = null;
    }
    for (const node of nodes) {
        let event_map;
        if (event_handlers.has(node)) {
            event_map = event_handlers.get(node);
        } else {
            console.warn('trying to remove event but no event registered on node');
            return;
        }
        if (event_map.hasOwnProperty(type)) {
            const new_handler_list = event_map[type].sub_handlers.filter(({s, h}) => s === subselector && h === handler);
            if (new_handler_list.length === event_map[type].sub_handlers.length) {
                console.warn('trying to remove event that was not registered');
                return;
            }
            if (new_handler_list.length === 0) {
                node.removeEventListener(type, event_map[type].handler);
                delete event_map[type];
            }
        } else {
            console.warn('trying to remove event but no event registered on node');
            return;
        }
        if (Object.keys(event_map).length === 0) {
            event_handlers.delete(node);
        }
    }
}


export function waitEvent(selector: string | Node | Node[] | NodeList | HTMLCollection, event: string, subselector: string | number = null, timeout: number = null) {
    if (typeof subselector === 'number' && timeout === null) {
        timeout = subselector;
        subselector = null;
    }
    return new Promise((resolve) => {
        let completed = false;
        let timeoutHandle = null;

        const handler = (e, el) => complete([e, el]);

        const complete = (result) => {
            if (completed) return;
            completed = true;
            off(selector, event, subselector as string, handler);
            if (timeoutHandle !== null) {
                window.clearTimeout(timeoutHandle);
            }
            resolve(result);
        }

        if (timeout !== null) {
            timeoutHandle = window.setTimeout(() => complete(null), timeout);
        }

        on(selector, event, subselector as string, handler);
    });
}


