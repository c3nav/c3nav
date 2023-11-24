type EventHandler = (e: Event, el: Node) => void;

declare function on(selector: string | Node | Node[] | NodeList | HTMLCollection, type: string, subselector: string | EventHandler, handler?: EventHandler): void;

declare function off(selector: string | Node | Node[] | NodeList | HTMLCollection, type: string, subselector: string | EventHandler, handler?: EventHandler): void;

declare var c3nav: any;
declare var mobileclient: any;
declare var L: any;


function c3nav_icon(name: string) {
    return name; // TODO
}

function wait(ms: number) {
    return new Promise(resolve =>
        window.setTimeout(() => resolve(null), ms));
}

function nextTick() {
    return wait(0);
}


function waitEvent(selector: string | Node | Node[] | NodeList | HTMLCollection, event: string, subselector: string | number = null, timeout: number = null) {
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


async function recoverPromise<T>(promise: Promise<T>): Promise<T | any> {
    try {
        return await promise;
    } catch (e) {
        return e;
    }
}


class OriginInput {
    root: HTMLElement;
    icon: HTMLElement;
    inputEl: HTMLInputElement;
    subtitle: HTMLElement;
    locateButton: HTMLElement;
    clearButton: HTMLElement;
    location: C3NavLocation = null;
    lastlocation: C3NavLocation = null;
    suggestion: C3NavLocation = null;
    origval: string = null;

    constructor(root: HTMLElement) {
        this.root = root;
        this.icon = this.root.querySelector('.icon');
        this.inputEl = this.root.querySelector('input');
        this.subtitle = this.root.querySelector('small');
        this.locateButton = this.root.querySelector('.locate');
        this.clearButton = this.root.querySelector('.clear');

        on(this.inputEl, 'blur', this.onblur);
        on(this.inputEl, 'input', this.oninput);
        on(this.inputEl, 'keydown', this.onkeydown);
        on(this.clearButton, 'click', this.clear);
        on(this.locateButton, 'click', this.locate);
    }

    set = (location: C3NavLocation) => {
        if (typeof location !== 'object') {
            throw new Error('invalid location, must be null or object');
        }
        if (location !== null && location.constructor !== ({}).constructor) {
            throw new Error('invalid location, must be plain object');
        }
        c3nav.sidebar.autocomplete.reset();
        this.root.classList.toggle('selected', !!location);
        this.root.classList.toggle('empty', !location);
        this.location = location;
        this.lastlocation = location;
        this.suggestion = null;
        this.origval = null;
        if (location) {
            this.icon.textContent = c3nav_icon(location.icon ?? 'place');
            this.inputEl.value = location.title;
            this.subtitle.innerText = location.subtitle;
        } else {
            this.icon.textContent = '';
            this.inputEl.value = '';
            this.subtitle.innerText = '';
        }
    }

    maybe_set = (location: C3NavLocation) => {
        if (this.root.matches('.empty')) return false;
        const orig_location = this.location;
        if (orig_location.id !== location.id) return false;
        const new_location = {
            ...orig_location,
            location
        };
        this.set(new_location);
        return true;
    }

    onblur = () => {
        if (this.suggestion) {
            // if it has a suggested location in it currently
            this.set(this.suggestion);
            c3nav.update_state_new();
        } else {
            // otherwise, forget the last location
            this.lastlocation = null;
        }
    }

    clear = () => {
        // clear this locationinput
        this.set(null);
        c3nav.update_state_new();
        this.inputEl.focus();
    }

    locate = async (e: MouseEvent) => {
        e.preventDefault();
        if (!window.mobileclient) {
            const content = document.querySelector('#app-ad').cloneNode(true) as HTMLElement;
            content.classList.remove('hidden');
            c3nav.modal.open(content);
            return;
        }
        if (typeof window.mobileclient.checkLocationPermission === 'function') {
            window.mobileclient.checkLocationPermission(true);
        }
        if (c3nav._current_user_location) {
            this.set(c3nav._current_user_location);
            c3nav.update_state_new();
        }

    }


    reset = () => {
        this.set(this.lastlocation);
        c3nav.update_state_new();
    }

    onkeydown = (e: KeyboardEvent) => {
        if (e.key === 'Escape') {
            // escape: reset the location input
            if (this.origval) {
                this.inputEl.value = this.origval;
                this.origval = null;
                this.suggestion = null;
                c3nav.sidebar.autocomplete.unfocus();
            } else {
                this.reset();
            }
        } else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
            this.origval = this.inputEl.value;
            let new_val;
            if (e.key === 'ArrowUp') {
                new_val = c3nav.sidebar.autocomplete.prev();
            } else {
                new_val = c3nav.sidebar.autocomplete.next();
            }
            if (!new_val) {
                // if there is no next element, restore original value
                this.inputEl.value = this.origval;
                this.suggestion = null;
            } else {
                // otherwise, save location to the input
                this.inputEl.value = new_val.querySelector('span').textContent;
                this.suggestion = c3nav.locations_by_id[new_val.dataset.id];
            }
        } else if (e.key === 'Enter') {
            // enter: select currently focused suggestion or first suggestion
            const selected = c3nav.sidebar.autocomplete.focused();
            if (!selected) return;
            this.set(c3nav.locations_by_id[selected.dataset.id]);
            c3nav.update_state_new();
            c3nav.fly_to_bounds(true);
        }
    }

    oninput = (e: InputEvent) => {
        this.origval = null;
        this.suggestion = null;
        const val = this.inputEl.value;
        this.root.classList.toggle('empty', val === '');

        if (this.root.matches('.selected')) {
            this.root.classList.remove('selected');
            this.location = null;
            c3nav.update_state_new();
        }

        c3nav.sidebar.autocomplete.input(val, this);
    }

    isSelected = () => {
        return this.root.classList.contains('selected');
    }
}

class DestinationInput extends OriginInput {
    randomButton: HTMLElement;

    constructor(root: HTMLElement) {
        super(root);
        this.randomButton = root.querySelector('button.random');

        on(this.randomButton, 'click', this.onRandomClick);
    }


    onRandomClick = async (e: MouseEvent) => {
        try {
            const {width, height} = this.root.getBoundingClientRect();
            const buttonRect = this.randomButton.getBoundingClientRect();
            const left = buttonRect.left + buttonRect.width / 2;
            const cover = <div style={{
                width: `${width}px`,
                height: `${height}px`,
                left: `${left}px`,
            }}></div>;
            this.root.append(cover);
            const new_left = 5 + buttonRect.width / 2;
            this.randomButton.style.left = `${buttonRect.left}px`;
            this.randomButton.classList.add('animating');
            await nextTick();
            cover.style.left = `${new_left}px`;
            this.randomButton.style.left = `5px`;
            await nextTick();
            const transitionEndAwaiter = waitEvent([cover, this.randomButton], 'transitionend', 350);
            const location = c3nav.choose_random_location();
            await transitionEndAwaiter;
            c3nav.sidebar.destination.set(location);
            c3nav.update_state(false);
            c3nav.fly_to_bounds(true);
            cover.style.left = `${width + buttonRect.width / 2}px`;
            this.randomButton.style.left = `${width}px`;
            await waitEvent([cover, this.randomButton], 'transitionend', 350);
            this.randomButton.classList.add('hidden');
            this.randomButton.classList.remove('animating');
            cover.remove();
            this.randomButton.style.removeProperty('left');
            await wait(100)
            this.randomButton.classList.remove('hidden');
        } catch (e) {
            console.log(e);
        }
    }
}

interface Geometry {

}

type LocationDisplayInfo = any;

interface C3NavLocation {
    // TODO
    type: string;
    display: LocationDisplayInfo[];
    geometry: Geometry;
    editor_url: string;
    id: number;
    icon?: string;
    subtitle: string;
    title: string;
}

type RouteItemDescription = [string, string];

interface RouteItem {
    descriptions: RouteItemDescription[];

}

interface Route {
    items: RouteItem[];
    destination: C3NavLocation;
    origin: C3NavLocation;

}


function c3nav_search(words: string[]): C3NavLocation[] {
    const matches = [];
    for (let i = 0; i < c3nav.locations.length; i++) {
        const location = c3nav.locations[i];
        let leading_words_count = 0;
        let words_total_count = 0;
        let words_start_count = 0;
        let nomatch = false;

        // each word has to be in the location
        for (const word of words) {
            if (location.match.indexOf(word) === -1) {
                nomatch = true;
                break;
            }
        }
        if (nomatch) continue;

        // how many words from the beginning are in the title
        for (let j = 0; j < words.length; j++) {
            let word = words[j];
            if (location.title_words[j] !== word &&
                (j !== words.length - 1 || location.title_words[j].indexOf(word) !== 0)) break;
            leading_words_count++;
        }

        // how many words in total can be found
        for (const word of words) {
            if (location.match.indexOf(' ' + word + ' ') !== -1) {
                words_total_count++;
            } else if (location.match.indexOf(' ' + word) !== -1) {
                words_start_count++;
            }
        }

        matches.push({
            location,
            leading_words_count,
            words_total_count,
            words_start_count
        });
        matches.push([location, leading_words_count, words_total_count, words_start_count, -location.title.length, i])
    }

    matches.sort((a, b) => {
        if (a[1] !== b[1]) return b[1] - a[1];
        if (a[2] !== b[2]) return b[2] - a[2];
        if (a[3] !== b[3]) return b[3] - a[3];
        if (a[4] !== b[4]) return b[4] - a[4];
        return a[5] - b[5];
    });

    return matches.map(match => match[0]);
}


class AutoComplete {
    root: HTMLElement;
    current_locationinput: OriginInput = null;
    last_words_key: string = null;

    constructor(root: HTMLElement) {
        this.root = root;

        on(this.root, 'mouseover', '.location', this.onmouseover);
        on(this.root, 'click', '.location', this.onclick);
    }

    onmouseover = (e: MouseEvent, el: HTMLElement) => {
        this.unfocus();
        el.classList.add('focus');
    }

    onclick = (e: MouseEvent, el: HTMLElement) => {
        this.current_locationinput.set(c3nav.locations_by_id[el.dataset.id]);
        c3nav.update_state_new();
        c3nav.fly_to_bounds(true);
    }

    reset = () => {
        // hide autocomplete
        this.unfocus();
        this.root.replaceChildren();
        this.last_words_key = null;
        this.current_locationinput = null;
    }

    unfocus = () => {
        for (const el of this.root.querySelectorAll('.location')) {
            el.classList.remove('focus');
        }
    }

    prevnext = (next: boolean) => {
        // arrows up
        const locations = [...this.root.querySelectorAll('.location')];
        if (!locations.length) return;

        // find focused element
        const current = locations.find(e => e.matches('.focus'));
        this.unfocus();

        // find next element
        let new_el;
        if (!current) {
            if (next) {
                new_el = locations[0];
            } else {
                new_el = locations[locations.length - 1];
            }
        } else {
            if (next) {
                new_el = current.nextSibling;
            } else {
                new_el = current.previousSibling;
            }
        }

        if (new_el) {
            new_el.classList.add('focus');
            return new_el;
        } else {
            return null;
        }
    }

    prev = () => this.prevnext(false)

    next = () => this.prevnext(true)

    focused = () => {
        const focused = this.root.querySelector('.location.focus');
        if (focused) {
            return focused;
        }
        return this.root.querySelector('.location:first-child');
    }

    input = (val: string, source: OriginInput) => {
        const val_trimmed = val.trim();
        const val_words = val_trimmed.toLowerCase().split(/\s+/);
        const val_words_key = val_words.join(' ');

        this.unfocus();
        this.current_locationinput = source;

        if (val_trimmed === '') {
            this.reset();
            return;
        }
        if (val_words_key === this.last_words_key) return;
        this.last_words_key = val_words_key;

        const matches = c3nav_search(val_words);
        const max_items = Math.min(matches.length, Math.floor(document.querySelector('#resultswrapper').getBoundingClientRect().height / 55)); // TODO this is not pretty

        this.root.replaceChildren();

        for (let i = 0; i < max_items; i++) {
            this.root.append(c3nav._build_location_html(matches[i]));
        }
    }
}

class LocationDetails {
    root: HTMLElement;
    detailsBody: HTMLElement;
    editor: HTMLLinkElement;
    reportIssue: HTMLLinkElement;
    reportMissing: HTMLLinkElement;

    id: number = null;

    constructor(root: HTMLElement) {
        this.root = root;
        this.detailsBody = this.root.querySelector('.details-body')
        this.editor = this.root.querySelector('.editor')
        this.reportIssue = this.root.querySelector('.report-issue');
        this.reportMissing = this.root.querySelector('.report-missing');

        on(root, 'click', '.close', this.close);
    }

    close = () => {
        c3nav.update_state_new({details: false});
    }


    async load(location: C3NavLocation) {
        if (this.id !== location.id) {
            this.setLoading(true);
            this.id = location.id;
            c3nav._clear_route_layers();
            try {
                const data = await c3nav.json_get(`/api/v2/locations/${location.id}/display`);
                if (this.id !== data.id) {
                    return;
                }
                this.setLocation(data);
                if (data.geometry && data.level) {
                    L.geoJSON(data.geometry, {
                        style: {
                            color: c3nav._primary_color,
                            fillOpacity: 0.1,
                        }
                    }).addTo(c3nav._routeLayers[data.level]);
                }
            } catch (e) {
                this.setError(e.message);
            }
        }
    }


    setLoading = (loading: boolean) => {
        this.root.classList.toggle('loading', loading);
    }

    setError = (error: string) => {
        this.detailsBody.textContent = `Error ${error}`;
        this.editor.classList.add('hidden');
        this.reportIssue.classList.add('hidden');
        this.reportMissing.classList.add('hidden');
        this.setLoading(false);
    }

    setLocation = (location: C3NavLocation) => {
        const dl = <dl/>;
        const clickhandler = id => e => {
            e.preventDefault();
            c3nav.sidebar.destination.set(c3nav.locations_by_id[id]);
            c3nav.update_state_new({details: true});
        }
        for (const line of location.display) {
            dl.append(<dt>{line[0]}</dt>);
            if (typeof line[1] === 'string') {
                dl.append(<dd>{line[1]}</dd>);
            } else if (line[1] === null || line.length === 0) {
                dl.append(<dd>-</dd>);
            } else {
                const sublocations = (line[1].length === undefined) ? [line[1]] : line[1];
                let content;
                for (const loc of sublocations) {
                    if (loc.can_search) {
                        content = <a href={`/l/${loc.slug}/details/`}
                                     onClick={clickhandler(loc.id)}>{loc.title}</a>;
                    } else {
                        content = <span>{loc.title}</span>;
                    }
                }
                dl.append(<dd>{content}</dd>);
            }
        }
        this.detailsBody.replaceChildren(dl);

        if (location.editor_url) {
            this.editor.href = location.editor_url;
            this.editor.classList.remove('hidden');
        } else {
            this.editor.classList.add('hidden');
        }

        if (location.geometry) {
            if (typeof location.id === 'number') {
                this.reportMissing.classList.add('hidden');
                this.reportIssue.classList.remove('hidden');
                this.reportIssue.href = `/report/l/${location.id}/`;
            } else {
                this.reportIssue.classList.add('hidden');
                this.reportMissing.classList.remove('hidden');
                this.reportMissing.href = `/report/l/${location.id}/`;
            }
        } else {
            this.reportIssue.classList.add('hidden');
            this.reportMissing.classList.add('hidden');
        }
        this.setLoading(false);
    }

}

class RouteDetails {
    root: HTMLElement;
    report: HTMLLinkElement;
    body: HTMLElement;

    constructor(root: HTMLElement) {
        this.root = root;
        this.report = root.querySelector('.report');
        this.body = root.querySelector('.details-body');

        on(root, 'click', '.close', this.close);
    }

    setIssueUrl(url: string) {
        this.report.href = url;
    }


    setLoading = (loading: boolean) => {
        this.root.classList.toggle('loading', loading);
    }

    setRoute(route: Route) {
        this.body.replaceChildren();
        this.body.append(c3nav._build_location_html(route.origin));
        for (const item of route.items) {
            for (const [icon, text] of item.descriptions) {
                this.body.append(<div className="routeitem">
                    {icon.indexOf('.') === -1
                        ? <span className="icon"><i className="material-icons">{icon}</i></span>
                        : <span className="icon"><img src={`/static/site/img/icons/${icon}`}/></span>}
                    <span>{text}</span>
                </div>);
            }
        }
        this.body.append(c3nav._build_location_html(route.destination));
        this.setLoading(false);
    }

    close = () => {
        c3nav.update_state_new({details: false});
    }
}

class RouteOptions {
    root;
    fields;

    constructor(root) {
        this.root = root;
        this.fields = root.querySelector('.route-options-fields');

        on(this.root, 'click', '.close', this.close);
        on(this.root, 'click', 'button', this.submit);
    }

    close = () => {
        c3nav.update_state_new({options: false});
    }

    submit = (e, el) => {
        const options = {};
        for (const field of this.root.querySelectorAll('.route-options-fields [name]')) {
            options[field.name] = field.value;
        }
        if (el.matches('.save')) {
            c3nav.json_post('/api/routing/options/', options)
        }
        c3nav.next_route_options = options;
        c3nav.update_state_new({options: false});
    }

    setLoading = (loading) => {
        this.root.classList.toggle('loading', loading);
    }

    setOptions = (options) => {
        this.fields.replaceChildren();
        for (const option of options) {
            const field_id = `option_id_${option.name}`;
            this.fields.append(<label htmlFor={field_id}>{option.label}</label>);
            let field;
            if (option.type === 'select') {
                field = <select name={option.name} id={field_id} value={option.value}>
                    {option.choices.map(choice => <option value={choice.name}>{choice.title}</option>)}
                </select>
            }
            this.fields.append(field);
        }
        this.setLoading(false);
    }
}

class RouteSummary {
    root;

    origin = null;
    destination = null;

    constructor(root) {
        this.root = root;

        on(this.root, 'click', '.options', this.onOptionsClick);
    }

    onOptionsClick = e => {
        c3nav.update_state_new({options: !c3nav.state.options});
    }

    setLoading = (loading) => {
        this.root.classList.toggle('loading', loading);
    }

    isLoading = () => {
        return this.root.classList.contains('loading');
    }

    setError = (error) => {
        this.root.querySelector('span').textContent = error;
        this.setLoading(false);
    }

    setSummary(summary, options_summary) {
        this.root.querySelector('span').textContent = summary;
        this.root.querySelector('em').textContent = options_summary;
        this.setLoading(false);
    }

}

class Sidebar {
    root;
    search;
    resultswrapper;
    origin;
    destination;
    autocomplete;
    locationDetails;
    routeDetails;
    routeOptions;
    locationButtons;
    routeSummary;
    routeSearchButtons;
    routeResultButtons;

    constructor(root) {
        this.root = root;
        this.search = root.querySelector('#search');
        this.resultswrapper = root.querySelector('#resultswrapper');
        this.locationButtons = root.querySelector('#location-buttons');
        this.routeSummary = new RouteSummary(root.querySelector('#route-summary'));
        this.routeSearchButtons = root.querySelector('#route-search-buttons');
        this.routeResultButtons = root.querySelector('#route-result-buttons');

        this.origin = new OriginInput(root.querySelector('#origin-input'));
        this.destination = new DestinationInput(root.querySelector('#destination-input'));
        this.autocomplete = new AutoComplete(root.querySelector('#autocomplete'));
        this.locationDetails = new LocationDetails(root.querySelector('#location-details'));
        this.routeDetails = new RouteDetails(root.querySelector('#route-details'));
        this.routeOptions = new RouteOptions(root.querySelector('#route-options'));


        on([this.locationButtons, this.routeResultButtons], 'click', '.details', this.onDetailsClick);
        on(this.locationButtons, 'click', '.share', this.onShareClick);
        on(this.locationButtons, 'click', '.route', this.onRouteClick);
        on([this.routeSearchButtons, this.routeResultButtons], 'click', '.swap', this.onSwapClick);
        on(this.routeSearchButtons, 'click', '.close', this.onCloseClick);
    }

    onDetailsClick = e => {
        c3nav.update_state_new({details: !c3nav.state.details});
    }

    onShareClick = e => {
        c3nav.modal.open(document.querySelector('main > .share-ui').outerHTML);
        c3nav._update_share_ui(false, location);
    }

    onRouteClick = e => {
        c3nav.update_state_new({routing: true});
    }

    onSwapClick = e => {
        const tmp = this.origin.location;
        this.origin.set(this.destination.location);
        this.destination.set(tmp);

        const offset = this.destination.root.getBoundingClientRect().top - this.origin.root.getBoundingClientRect().top;
        this.origin.root.style.transition = '';
        this.destination.root.style.transition = '';
        this.origin.root.style.top = `${offset}px`;
        this.destination.root.style.top = `-${offset}px`;
        window.setTimeout(() => {
            this.origin.root.style.transition = `top 150ms`;
            this.destination.root.style.transition = `top 150ms`;
            this.origin.root.style.top = 0;
            this.destination.root.style.top = 0;
        }, 0);
        c3nav.update_state_new();
    }

    onCloseClick = e => {
        if (this.origin.isSelected() && !this.destination.isSelected()) {
            this.destination.set(this.origin.location);
        }
        c3nav.update_state_new({routing: false});
    }

    unfocusSearch = () => {
        this.search.classList.remove('focused');
    }

    focusSearch = () => {
        this.search.classList.add('focused');
    }


}

class Modal {
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

class Settings {
    backend;
    prefix;

    constructor(backend, prefix = '') {
        this.backend = backend;
        this.prefix = prefix;
    }

    clear() {
        try {
            if (this.prefix === '') {
                this.backend.clear();
            } else {
                for (let i = 0; i < this.backend.length; i++) {
                    const key = this.backend.key(i);
                    if (key.startsWith(this.prefix)) {
                        this.backend.removeItem(key)
                    }
                }
            }
        } catch (e) {
            console.warn('failed to clear settings', e);
        }
    }

    set(name, value) {
        try {
            this.backend.setItem(`${this.prefix}${name}`, JSON.stringify(value));
        } catch (e) {
            console.warn('failed to write setting', e);
        }
    }

    get(name, defaultValue = null) {
        try {
            const val = this.backend.getItem(`${this.prefix}${name}`);
            if (val === null) {
                return defaultValue;
            } else {
                try {
                    return JSON.parse(val);
                } catch (e) {
                    console.warn('retrieved setting is not valid json');
                    return defaultValue;
                }
            }
        } catch (e) {
            console.warn('failed to read setting');
            return defaultValue;
        }
    }
}


class State {
    center = null;
    zoom = 1;
    destination = null;
    origin = null;
    routing = null;
    sidebar = false;
    details = false;
    level = 0;
    modal = false;
    nearby = false;
    options = false;

    constructor(initial) {
        this.assign(initial);
    }

    assign(properties) {
        let changed = false;
        for (const prop of ['center', 'zoom', 'destination', 'origin', 'routing', 'sidebar', 'details', 'level', 'modal', 'nearby', 'options']) {
            if (prop in properties) {
                if (this[prop] !== properties[prop]) {
                    changed = true;
                }
                this[prop] = properties[prop];
            }
        }
        return changed;
    }


    push = (new_state, replace) => {
        const had_sidebar = c3nav.sidebar;
        const changed = this.assign(new_state);
        if (!replace && !changed) return;

        const url = this.build_url(c3nav.embed);
        const embed_link = document.querySelector('a.embed-link') as HTMLLinkElement;
        if (embed_link) {
            embed_link.href = this.build_url();
        }

        if (replace || (!c3nav.sidebar && !had_sidebar)) {
            history.replaceState({...this}, '', url);
        } else {
            history.pushState({...this}, '', url);
        }

        c3nav.maybe_load_site_update();
    }

    build_url = (embed = false) => {
        let url;
        let loc = false;
        let route = false;
        if (this.routing) {
            if (this.origin && this.destination) {
                url = `/r/${this.origin.slug}/${this.destination.slug}/`;
                route = true;
            } else if (!this.origin && !this.destination) {
                url = '/r/';
                route = true;
            } else if (this.origin && !this.destination) {
                url = `/o/${this.origin.slug}/`;
            } else if (!this.origin && this.destination) {
                url = `/d/${this.destination.slug}/`;
            }
        } else {
            if (this.destination) {
                url = `/l/${this.destination.slug}/`;
                loc = true;
            } else {
                url = '/';
            }
        }
        if (this.details && (route || loc)) {
            url += 'details/'
        }
        if (this.nearby && loc) {
            url += 'nearby/'
        }
        if (this.options && route) {
            url += 'options/'
        }
        if (this.center) {
            url += `@${c3nav.map.level_labels_by_id[this.level]},${this.center[0]},${this.center[1]},${this.zoom}`;
        }
        if (embed) {
            return `/embed${url}`;
        } else {
            return url;
        }
    }
}

class Messages {
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

class C3NavMap {
    root;
    anywhereButtons;
    locationButtons;
    map;

    bounds;
    levels;
    initial_level;

    level_labels_by_id = {};
    visible_map_locations = [];

    locationLayers = {};
    locationLayerBounds = {};
    detailLayers = {};
    routeLayers = {};
    routeLayerBounds = {};
    userLocationLayers = {};
    firstRouteLevel = null;

    location_point_overrides = {};

    levelControl;
    labelControl;
    labelLayer;

    tile_server;

    anywherePopup = null;

    constructor(root: HTMLElement) {
        this.root = root;
        this.tile_server = root.dataset.tileServer ?? '/map/';

        this.anywhereButtons = document.querySelector('#anywhere-popup-buttons').cloneNode(true);
        this.locationButtons = document.querySelector('#location-popup-buttons').cloneNode(true);
        this.bounds = JSON.parse(this.root.dataset.bounds);
        this.levels = JSON.parse(this.root.dataset.levels);
        if (this.root.dataset.hasOwnProperty('initialLevel')) {
            this.initial_level = parseInt(this.root.dataset.initialLevel);
        } else if (this.levels.length > 0) {
            this.initial_level = this.levels[0][0];
        } else {
            this.initial_level = 0;
        }

        for (const level of this.levels) {
            this.level_labels_by_id[level[0]] = level[1];
        }

    }

    init = ({width, height}) => {
        const minZoom = Math.log2(Math.max(0.25, Math.min(
            (width) / (this.bounds[1][0] - this.bounds[0][0]),
            (height) / (this.bounds[1][1] - this.bounds[0][1])
        )));

        const factor = Math.pow(2, minZoom);
        const maxBounds = [
            [this.bounds[0][0] - 600 / factor, this.bounds[0][1] - 200 / factor],
            [this.bounds[1][0] + 600 / factor, this.bounds[1][1] + 200 / factor]
        ];

        this.map = L.map(this.root, {
            renderer: L.svg({padding: 2}),
            zoom: 0,
            maxZoom: 5,
            minZoom: minZoom,
            crs: L.CRS.Simple,
            maxBounds: L.GeoJSON.coordsToLatLngs(maxBounds),
            zoomSnap: 0,
            zoomControl: false,
            attributionControl: !window.mobileclient,
        });
        if (!window.mobileclient) this.map.attributionControl.setPrefix(document.querySelector('#attributions').innerHTML);

        if (!('ontouchstart' in window || navigator.maxTouchPoints)) {
            this.root.classList.remove('leaflet-touch');
        }


        let initial_bounds;
        if (this.root.dataset.hasOwnProperty('initialBounds')) {
            const bounds = JSON.parse(this.root.dataset.initialBounds);
            initial_bounds = [bounds.slice(0, 2), bounds.slice(2)];
        } else {
            initial_bounds = this.bounds;
        }

        this.map.fitBounds(L.GeoJSON.coordsToLatLngs(initial_bounds), c3nav._add_map_padding({}));

        this.map.on('moveend', this.map_moved);
        this.map.on('zoomend', this.map_zoomed);

        // setup scale control
        L.control.scale({imperial: false}).addTo(this.map);

        // setup level control
        this.levelControl = new LevelControl().addTo(this.map);
        for (const level of this.levels.toReversed()) {
            const layerGroup = this.levelControl.addLevel(level[0], level[1]);
            this.detailLayers[level[0]] = L.layerGroup().addTo(layerGroup);
            this.locationLayers[level[0]] = L.layerGroup().addTo(layerGroup);
            this.routeLayers[level[0]] = L.layerGroup().addTo(layerGroup);
            this.userLocationLayers[level[0]] = L.layerGroup().addTo(layerGroup);
        }
        this.levelControl.finalize();
        this.levelControl.setLevel(this.initial_level);

        this.labelLayer = L.LayerGroup.collision({margin: 5}).addTo(this.map);
        this.labelControl = new LabelControl().addTo(this.map);


        if (c3nav.settings.get('hideLabels', false)) {
            this.labelControl.hideLabels();
        }


        L.control.zoom({
            position: 'bottomright'
        }).addTo(this.map);

        // setup grid control
        if (this.root.dataset.hasOwnProperty('grid')) {
            c3nav._gridLayer = new L.SquareGridLayer(JSON.parse(this.root.dataset.grid));
            c3nav._gridControl = new SquareGridControl().addTo(this.map);
        }

        // setup user location control
        c3nav._userLocationControl = new UserLocationControl().addTo(this.map);


        this.map.on('click', this.click_anywhere);

        on(this.root, 'click', '.location-popup .button-clear', this.popup_button_click);
    }

    map_moved = () => {
        c3nav.update_map_state();
        c3nav.update_location_labels();
    }

    map_zoomed = () => {
        c3nav.update_map_state();
        c3nav.update_location_labels();
    }

    click_anywhere = e => {
        if (e.originalEvent.target !== this.root) return;

        const popup = L.popup(c3nav._add_map_padding({
                className: 'location-popup',
                maxWidth: 500
            }, 'autoPanPaddingTopLeft', 'autoPanPaddingBottomRight')),
            name = c3nav._latlng_to_name(e.latlng);
        const buttons = this.anywhereButtons;
        buttons.querySelector('.report').href = `/report/l/${name}/`;
        buttons.querySelector('.set-position').href = `/positions/set/${name}/`;
        popup.setLatLng(e.latlng).setContent(buttons.innerHTML); // TODO: try using a document fragment
        this.anywherePopup = popup;
        popup.on('remove', () => {
            this.anywherePopup = null
        }).openOn(this.map);
    }

    click_anywhere_load = async nearby => {
        if (!this.anywherePopup) return;
        const latlng = this.anywherePopup.getLatLng();
        this.anywherePopup.remove();
        const popup = L.popup()
            .setLatLng(latlng)
            .setContent(<div className="loader"/>);
        const name = c3nav._latlng_to_name(latlng);
        this.anywherePopup = popup;
        popup.on('remove', () => {
            this.anywherePopup = null
        }).openOn(this.map);

        try {
            const data = await c3nav.json_get(`/api/v2/map/locations/${name}/`);
            if (this.anywherePopup !== popup || !popup.isOpen()) return;
            popup.remove();
            if (nearby) {
                c3nav.sidebar.destination.set(data);
                c3nav.update_state(false, false, false, false, true);
            } else {
                const newpopup = L.popup(c3nav._add_map_padding({
                    className: 'location-popup',
                    maxWidth: 500
                }, 'autoPanPaddingTopLeft', 'autoPanPaddingBottomRight'));
                const buttons = this.locationButtons.cloneNode(true);
                buttons.querySelector('.report-issue').remove();
                buttons.querySelector('.report').href = `/report/l/${data.id}/`;
                newpopup.setLatLng(latlng)
                    .setContent(c3nav._build_location_html(data).outerHTML + buttons.innerHTML);
                this.anywherePopup = newpopup;
                newpopup.on('remove', () => {
                    this.anywherePopup = null
                }).openOn(this.map);
            }
        } catch (e) {
            console.log(e);
            popup.remove();
        }
    }

    popup_button_click = (e, el) => {
        e.stopPropagation();
        const $location = [...el.parentElement.parentElement.children].find(x => x.matches('.location'));
        if ($location) {
            let location = c3nav.locations_by_id[parseInt($location.dataset.id)];
            if (!location) {
                location = JSON.parse($location.dataset.location);
            }
            if (el.matches('.as-location')) {
                c3nav.sidebar.destination.set(location);
                c3nav.update_state(false);
            } else if (el.matches('.share')) {
                c3nav._buttons_share_click(location);
            } else if (el.matches('a')) {
                c3nav.link_handler_modal.call(this, e, el);
            } else {
                const locationinput = el.matches('.as-origin') ? c3nav.sidebar.origin : c3nav.sidebar.destination,
                    other_locationinput = el.matches('.as-origin') ? c3nav.sidebar.destination : c3nav.sidebar.origin,
                    other_location = other_locationinput.location;
                locationinput.set(location);
                if (other_location && (other_location.id === location.id || (other_location.locations && other_location.locations.includes(location.id)))) {
                    other_locationinput.set(null);
                }
                c3nav.update_state(true);
            }
            if (this.anywherePopup) this.anywherePopup.remove();
        } else {
            if (el.matches('.select-point')) {
                this.click_anywhere_load(false);
            } else if (el.matches('.show-nearby')) {
                this.click_anywhere_load(true);
            } else if (el.matches('a')) {
                c3nav.link_handler_modal.call(this, e, el);
            }
        }
    }

    remove_popup = () => {
        if (this.anywherePopup) {
            this.anywherePopup.remove();
        }
    }

    add_location = (location, icon, no_geometry = false) => {
        if (!location) {
            // if location is not in the searchable list...
            return;
        }
        if (location.dynamic) {
            if (!('available' in location)) {
                c3nav.json_get(`/api/v2/map/get_position/${location.id}/`)
                    .then(c3nav._dynamic_location_loaded);
                return;
            } else if (!location.available) {
                return;
            }
        }
        // add a location to the map as a marker
        if (location.locations) {
            const bounds = {};
            for (const loc of location.locations) {
                c3nav._merge_bounds(bounds, this.add_location(c3nav.locations_by_id[loc], icon, true));
            }
            return bounds;
        }

        if (!no_geometry && this.visible_map_locations.indexOf(location.id) === -1) {
            this.visible_map_locations.push(location.id);
            c3nav.json_get(`/api/v2/map/locations/${location.id}/geometry/`)
                .then(c3nav._location_geometry_loaded)
        }

        if (!location.point) return;

        const point = this.location_point_overrides[location.id] || location.point.slice(1);
        const latlng = L.GeoJSON.coordsToLatLng(point);
        const buttons = this.locationButtons.cloneNode(true);
        if (typeof location.id == 'number') {
            buttons.querySelector('.report-missing').remove();
        } else {
            buttons.querySelector('.report-issue').remove();
        }
        buttons.querySelector('.report').href = `/report/l/${location.id}/`;

        L.marker(latlng, {
            icon: icon
        }).bindPopup(c3nav._build_location_html(location).outerHTML + buttons.innerHTML, c3nav._add_map_padding({
            className: 'location-popup',
            maxWidth: 500
        }, 'autoPanPaddingTopLeft', 'autoPanPaddingBottomRight')).addTo(c3nav.map.locationLayers[location.point[0]]);

        const result = {};
        result[location.point[0]] = L.latLngBounds(
            location.bounds ? L.GeoJSON.coordsToLatLngs(location.bounds) : [latlng, latlng]
        );
        return result;
    }

    get center() {
        return this.map.getCenter();
    }

    get zoom() {
        return this.map.getZoom();
    }

    get view_bounds() {
        return this.map.getBounds();
    }

    limitCenter = (center, zoom) => {
        return this.map._limitCenter(center, zoom, this.map.options.maxBounds);
    }

    getBoundsCenterZoom = (bounds, options) => this.map._getBoundsCenterZoom(bounds, options);

    setView = (center, zoom, options) => this.map.setView(center, zoom, options)

    flyTo = (center, zoom, options) => this.map.flyTo(center, zoom, options)

    fly_to_bounds = (replace_state, nofly) => {
        let level = this.levelControl.currentLevel;
        let bounds = null;
        if (this.firstRouteLevel) {
            level = this.firstRouteLevel;
            bounds = this.routeLayerBounds[level];
        } else if (this.locationLayerBounds[level]) {
            bounds = this.locationLayerBounds[level];
        } else {
            for (const level_id in this.locationLayers) {
                if (this.locationLayerBounds[level_id]) {
                    bounds = this.locationLayerBounds[level_id];
                    level = level_id;
                }
            }
        }
        this.levelControl.setLevel(level);
        if (bounds) {
            const target = this.getBoundsCenterZoom(bounds, c3nav._add_map_padding({}));
            const center = this.limitCenter(target.center, target.zoom);
            this.map.flyTo(center, target.zoom, nofly ? {
                animate: false,
            } : {
                duration: 1,
            });
            if (replace_state) {
                c3nav.update_map_state(true, level, center, target.zoom);
            }
        }
    }

    add_line_to_route = (level: number, coords: [[number, number], [number, number]], gray: boolean, link_to_level: boolean) => {
        if (coords.length < 2) {
            console.warn('invalid coords');
            return;
        }
        const latlngs = L.GeoJSON.coordsToLatLngs(c3nav._smooth_line(coords));
        const routeLayer = this.routeLayers[level];
        const line = L.polyline(latlngs, {
            color: gray ? '#888888' : c3nav._primary_color,
            dashArray: (gray || link_to_level) ? '7' : null,
            interactive: false,
            smoothFactor: 0.5
        }).addTo(routeLayer);
        const bounds = {};
        bounds[level] = line.getBounds();

        c3nav._merge_bounds(this.routeLayerBounds, bounds);

        if (link_to_level) {
            L.polyline(latlngs, {
                opacity: 0,
                weight: 15,
                interactive: true
            })
                .addTo(routeLayer)
                .on('click', () => {
                    this.levelControl.setLevel(link_to_level);
                });
        }

    }

    add_location_point_override = (location: C3NavLocation, item) => {
        if (location.type === 'level' || location.type === 'space' || location.type === 'area') {
            this.location_point_overrides[location.id] = item.coordinates.slice(0, -1);
            return true;
        }
        return false;
    }

    update_locations = (single) => {
        for (const level_id in this.locationLayers) {
            this.locationLayers[level_id].clearLayers();
        }

        const bounds = {};
        const origin = c3nav.sidebar.origin.location;
        const destination = c3nav.sidebar.destination.location;

        if (origin) {
            c3nav._merge_bounds(bounds, this.add_location(origin, single ? new L.Icon.Default() : c3nav.originIcon));
        }
        if (destination) {
            c3nav._merge_bounds(bounds, this.add_location(destination, single ? new L.Icon.Default() : c3nav.destinationIcon));
        }
        const done = [];
        if (c3nav.state.nearby && destination && 'areas' in destination) {
            if (destination.space) {
                c3nav._merge_bounds(bounds, this.add_location(c3nav.locations_by_id[destination.space], c3nav.nearbyIcon, true));
            }
            if (destination.near_area) {
                done.push(destination.near_area);
                c3nav._merge_bounds(bounds, this.add_location(c3nav.locations_by_id[destination.near_area], c3nav.nearbyIcon, true));
            }
            for (var area of destination.areas) {
                done.push(area);
                c3nav._merge_bounds(bounds, this.add_location(c3nav.locations_by_id[area], c3nav.nearbyIcon, true));
            }
            for (var location of destination.nearby) {
                if (location in done) continue;
                c3nav._merge_bounds(bounds, this.add_location(c3nav.locations_by_id[location], c3nav.nearbyIcon, true));
            }
        }
        this.locationLayerBounds = bounds;
    }

}


const LOCALSTORAGE_SESSION_KEY = 'c3nav_session_token';

interface SessionChangeEventData {
    token: string;
    logout: boolean;
}

function make_session_change_event(token: string, logout: boolean) {
    return new CustomEvent<SessionChangeEventData>('sessionchanged', {
        detail: {
            token,
            logout
        }
    });
}


class C3NavApi extends EventTarget {
    constructor() {
        super();
        window.addEventListener('storage', e => {
            if (e.key !== LOCALSTORAGE_SESSION_KEY) {
                return;
            }
            this.dispatchEvent(make_session_change_event(e.newValue, e.oldValue !== 'anonymous'));
        });
        this.get_auth_session().then(data => {
            localStorage.setItem(LOCALSTORAGE_SESSION_KEY, data.token);
            this.dispatchEvent(make_session_change_event(data.token, false));
        });
    }

    private get_auth_session = async () => {
        const response = await fetch('/api/v2/auth/session', {
            credentials: 'same-origin'
        });
        return await response.json();
    }
}


const LabelControl = L.Control.extend({
    options: {
        position: 'bottomright',
        addClasses: ''
    },

    onAdd: function () {
        this._container = L.DomUtil.create('div', 'leaflet-control-labels leaflet-bar ' + this.options.addClasses);
        this._button = L.DomUtil.create('a', 'material-icons', this._container);
        on(this._button, 'click', this.toggleLabels);
        on(this._button, 'dblclick', e => e.stopPropagation());
        this._button.innerText = c3nav._map_material_icon('label');
        this._button.href = '#';
        this._button.classList.toggle('control-disabled', false);
        this.labelsActive = true;
        return this._container;
    },

    toggleLabels: function (e) {
        if (e) e.preventDefault();
        if (c3nav.map.labelControl.labelsActive) {
            c3nav.map.labelControl.hideLabels();
        } else {
            c3nav.map.labelControl.showLabels();
        }
    },

    showLabels: function () {
        if (this.labelsActive) return;
        c3nav.map.labelLayer.addTo(this._map);
        this._button.innerText = c3nav._map_material_icon('label');
        this._button.classList.toggle('control-disabled', false);
        this.labelsActive = true;
        c3nav.settings.set('hideLabels', false);
        c3nav.update_location_labels();
    },

    hideLabels: function () {
        if (!this.labelsActive) return;
        c3nav.map.labelLayer.clearLayers();
        c3nav.map.labelLayer.remove();
        this._button.innerText = c3nav._map_material_icon('label_outline');
        this._button.classList.toggle('control-disabled', true);
        this.labelsActive = false;
        c3nav.settings.set('hideLabels', true);
    }
});

const LevelControl = L.Control.extend({
    options: {
        position: 'bottomright',
        addClasses: ''
    },

    onAdd: function () {
        this._container = L.DomUtil.create('div', 'leaflet-control-levels leaflet-bar ' + this.options.addClasses);
        this._tileLayers = {};
        this._overlayLayers = {};
        this._levelButtons = {};
        this.currentLevel = null;
        return this._container;
    },

    createTileLayer: function (id) {
        return L.tileLayer(`${c3nav.map.tile_server}${id}/{z}/{x}/{y}.png`, {
            minZoom: -2,
            maxZoom: 5,
            bounds: L.GeoJSON.coordsToLatLngs(c3nav.map.bounds)
        });
    },
    addLevel: function (id, title) {
        this._tileLayers[id] = this.createTileLayer(id);
        const overlay = L.layerGroup();
        this._overlayLayers[id] = overlay;

        const link = L.DomUtil.create('a', '', this._container);
        link.innerHTML = title;
        link.level = id;
        link.href = '#';

        L.DomEvent
            .on(link, 'mousedown dblclick', L.DomEvent.stopPropagation)
            .on(link, 'click', this._levelClick, this);

        this._levelButtons[id] = link;
        return overlay;
    },

    setLevel: function (id) {
        if (id === this.currentLevel) return true;
        if (this._tileLayers[id] === undefined) return false;

        if (this.currentLevel) {
            this._tileLayers[this.currentLevel].remove();
            this._overlayLayers[this.currentLevel].remove();
            L.DomUtil.removeClass(this._levelButtons[this.currentLevel], 'current');
        }
        this._tileLayers[id].addTo(this._map);
        this._overlayLayers[id].addTo(this._map);
        L.DomUtil.addClass(this._levelButtons[id], 'current');
        this.currentLevel = id;
        return true;
    },

    _levelClick: function (e) {
        e.preventDefault();
        e.stopPropagation();
        this.setLevel(e.target.level);
        c3nav.update_map_state();
        c3nav.update_location_labels();
    },

    finalize: function () {
        const buttons = this._container.querySelectorAll('a');
        for (const button of buttons) {
            button.classList.add('current');
        }
        const width = Math.max(...[...buttons].map(b => b.clientWidth));
        for (const button of buttons) {
            button.style.width = `${width}px`;
            button.classList.remove('current');
        }
    },

    reloadMap: function () {
        const old_tile_layer = this._tileLayers[this.currentLevel];
        const new_tile_layer = this.createTileLayer(this.currentLevel);
        this._tileLayers[this.currentLevel] = new_tile_layer;
        new_tile_layer.addTo(this._map);
        window.setTimeout(function () {
            old_tile_layer.remove();
        }, 2000);
    }
});

const UserLocationControl = L.Control.extend({
    options: {
        position: 'bottomright',
        addClasses: ''
    },

    onAdd: function () {
        this._container = L.DomUtil.create('div', 'leaflet-control-user-location leaflet-bar ' + this.options.addClasses);
        this._button = L.DomUtil.create('a', 'material-icons', this._container);
        this._button.innerHTML = c3nav._map_material_icon(c3nav.hasLocationPermission() ? 'location_searching' : 'location_disabled');
        this._button.classList.toggle('control-disabled', !c3nav.hasLocationPermission());
        this._button.href = '#';

        L.DomEvent.on(this._button, 'click', c3nav._goto_user_location_click);
        L.DomEvent.on(this._button, 'dblclick', e => e.stopPropagation());

        this.currentLevel = null;
        return this._container;
    }
});


const SquareGridControl = L.Control.extend({
    options: {
        position: 'bottomright',
        addClasses: ''
    },

    onAdd: function () {
        this._container = L.DomUtil.create('div', 'leaflet-control-grid-layer leaflet-bar ' + this.options.addClasses);
        this._button = L.DomUtil.create('a', 'material-icons', this._container);
        on(this._button, 'click', this.toggleGrid);
        on(this._button, 'dblclick', e => e.stopPropagation());
        this._button.innerText = c3nav._map_material_icon('grid_off');
        this._button.href = '#';
        this._button.classList.toggle('control-disabled', true);
        this.gridActive = false;
        if (c3nav.settings.get('showGrid', false)) {
            this.showGrid();
        }
        return this._container;
    },

    toggleGrid: function (e) {
        if (e) e.preventDefault();
        if (c3nav._gridControl.gridActive) {
            c3nav._gridControl.hideGrid();
        } else {
            c3nav._gridControl.showGrid();
        }
    },

    showGrid: function () {
        if (this.gridActive) return;
        c3nav._gridLayer.addTo(this._map);
        this._button.innerText = c3nav._map_material_icon('grid_on');
        this._button.classList.toggle('control-disabled', false);
        this.gridActive = true;
        c3nav.settings.set('showGrid', true);
    },

    hideGrid: function () {
        if (!this.gridActive) return;
        c3nav._gridLayer.remove();
        this._button.innerText = c3nav._map_material_icon('grid_off');
        this._button.classList.toggle('control-disabled', true);
        this.gridActive = false;
        c3nav.settings.set('showGrid', false);
    }
});


L.SquareGridLayer = L.Layer.extend({
    initialize: function (config) {
        this.config = config;
    },

    onAdd: function () {
        this._container = L.DomUtil.create('div', 'leaflet-pane c3nav-grid');
        this.getPane().appendChild(this._container);

        this.cols = [];
        this.rows = [];
        for (let i = 0; i < this.config.cols.length; i++) {
            const elem = L.DomUtil.create('div', 'c3nav-grid-column');
            const label = String.fromCharCode(65 + (this.config.invert_x ? (this.config.cols.length - i - 2) : i));
            if (i < this.config.cols.length - 1) {
                elem.innerHTML = '<span>' + label + '</span><span>' + label + '</span>';
            }
            this._container.appendChild(elem);
            this.cols.push(elem);
        }
        for (let i = 0; i < this.config.rows.length; i++) {
            const elem = L.DomUtil.create('div', 'c3nav-grid-row');
            const label = (this.config.invert_y ? (this.config.rows.length - i) : i);
            if (i > 0) {
                elem.innerHTML = '<span>' + label + '</span><span>' + label + '</span>';
            }
            this._container.appendChild(elem);
            this.rows.push(elem);
        }

        this._updateGrid();

        this._map.on('viewreset zoom move zoomend moveend', this._update, this);
    },

    onRemove: function (map) {
        L.DomUtil.remove(this._container);
        this.cols = [];
        this.rows = [];
        map.off('viewreset zoom move zoomend moveend', this._update, this);
    },

    _update: function (e) {
        this._updateGrid(e.target);
    },

    _updateGrid: function () {
        if (!this.cols || this.cols.length === 0) return;
        const mapSize = this._map.getSize();
        const panePos = this._map._getMapPanePos();
        const sidebarStart = c3nav.sidebar.root.offsetWidth + 15;
        const searchHeight = c3nav.sidebar.search.offsetHeight + 10;
        const controlsWidth = (document.querySelector('.leaflet-control-zoom') as HTMLElement).offsetWidth + 10;
        const attributionStart = mapSize.x + (document.querySelector('.leaflet-control-attribution') as HTMLElement).offsetWidth - 16;
        const bottomRightStart = mapSize.y - (document.querySelector('.leaflet-bottom.leaflet-right') as HTMLElement).offsetHeight - 24;
        let lastCoord = null;
        this._container.style.width = mapSize.x + 'px';
        this._container.style.height = mapSize.y + 'px';
        this._container.style.left = (-panePos.x) + 'px';
        this._container.style.top = (-panePos.y) + 'px';
        for (let i = 0; i < this.config.cols.length; i++) {
            let coord = this._map.latLngToContainerPoint([0, this.config.cols[i]], this._map.getZoom()).x;
            coord = Math.min(mapSize.x, Math.max(-1, coord));
            this.cols[i].style.left = coord + 'px';
            if (i > 0) {
                let size = coord - lastCoord;
                let center = (lastCoord + coord) / 2;
                if (size > 0) {
                    this.cols[i - 1].style.display = '';
                    this.cols[i - 1].style.width = size + 'px';
                    this.cols[i - 1].style.paddingTop = Math.max(0, Math.min(searchHeight, (sidebarStart - center) / 15 * searchHeight)) + 'px';
                    this.cols[i - 1].style.paddingBottom = Math.max(0, Math.min(16, (center - attributionStart))) + 'px';
                } else {
                    this.cols[i - 1].style.display = 'none';
                }
            }
            lastCoord = coord;
        }
        for (let i = 0; i < this.config.rows.length; i++) {
            let coord = this._map.latLngToContainerPoint([this.config.rows[i], 0], this._map.getZoom()).y;
            coord = Math.min(mapSize.y, Math.max(-1, coord));
            this.rows[i].style.top = coord + 'px';
            if (i > 0) {
                let size = lastCoord - coord;
                let center = (lastCoord + coord) / 2;
                if (size > 0) {
                    this.rows[i].style.display = '';
                    this.rows[i].style.height = size + 'px';
                    this.rows[i].style.paddingRight = Math.max(0, Math.min(controlsWidth, (center - bottomRightStart) / 16 * controlsWidth)) + 'px';
                } else {
                    this.rows[i].style.display = 'none';
                }
            }
            lastCoord = coord;
        }
    }
});


