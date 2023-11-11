function c3nav_icon(name) {
    return name; // TODO
}

class LocationInput {
    sidebar;
    root;
    icon;
    inputEl;
    subtitle;
    locateButton;
    clearButton;
    location = null;
    lastlocation = null;
    suggestion = null;
    origval = null;

    constructor(root, sidebar) {
        this.sidebar = sidebar;
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

    set = (location) => {
        if (typeof location !== 'object') {
            throw new Error('invalid location, must be null or object');
        }
        if (location !== null && location.constructor !== ({}).constructor) {
            throw new Error('invalid location, must be plain object');
        }
        this.sidebar.autocomplete.reset();
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

    maybe_set = (location) => {
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

    locate = async (e) => {
        e.preventDefault();
        if (window.fake_location) {
            const location = await window.fake_location();
            c3nav._set_user_location(location);
        } else {
            if (!window.mobileclient) {
                const content = document.querySelector('#app-ad').cloneNode(true);
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
    }


    reset = () => {
        this.set(this.lastlocation);
        c3nav.update_state_new();
    }

    onkeydown = e => {
        if (e.key === 'Escape') {
            // escape: reset the location input
            if (this.origval) {
                this.inputEl.value = this.origval;
                this.origval = null;
                this.suggestion = null;
                this.sidebar.autocomplete.unfocus();
            } else {
                this.reset();
            }
        } else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
            this.origval = this.inputEl.value;
            let new_val;
            if (e.key === 'ArrowUp') {
                new_val = this.sidebar.autocomplete.prev();
            } else {
                new_val = this.sidebar.autocomplete.next();
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
            const selected = this.sidebar.autocomplete.focused();
            if (!selected) return;
            this.set(c3nav.locations_by_id[selected.dataset.id]);
            c3nav.update_state_new();
            c3nav.fly_to_bounds(true);
        }
    }

    oninput = e => {
        this.origval = null;
        this.suggestion = null;
        const val = this.inputEl.value;
        this.root.classList.toggle('empty', val === '');

        if (this.root.matches('.selected')) {
            this.root.classList.remove('selected');
            this.location = null;
            c3nav.update_state_new();
        }

        this.sidebar.autocomplete.input(val, this);
    }

    isSelected = () => {
        return this.root.classList.contains('selected');
    }
}

function c3nav_search(words) {
    const matches = [];
    for (let i = 0; i < c3nav.locations.length; i++) {
        var location = c3nav.locations[i],
            leading_words_count = 0,
            words_total_count = 0,
            words_start_count = 0,
            nomatch = false,
            word, j;

        // each word has to be in the location
        for (j = 0; j < words.length; j++) {
            word = words[j];
            if (location.match.indexOf(word) === -1) {
                nomatch = true;
                break;
            }
        }
        if (nomatch) continue;

        // how many words from the beginning are in the title
        for (j = 0; j < words.length; j++) {
            word = words[j];
            if (location.title_words[j] !== word &&
                (j !== words.length - 1 || location.title_words[j].indexOf(word) !== 0)) break;
            leading_words_count++;
        }

        // how many words in total can be found
        for (j = 0; j < words.length; j++) {
            word = words[j];
            if (location.match.indexOf(' ' + word + ' ') !== -1) {
                words_total_count++;
            } else if (location.match.indexOf(' ' + word) !== -1) {
                words_start_count++;
            }
        }

        matches.push([location, leading_words_count, words_total_count, words_start_count, -location.title.length, i])
    }

    matches.sort(c3nav._locationinput_matches_compare);

    return matches;
}


class AutoComplete {
    root;
    sidebar;
    current_locationinput = null;
    last_words_key = null;

    constructor(root, sidebar) {
        this.root = root;
        this.sidebar = sidebar;

        on(this.root, 'mouseover', '.location', this.onmouseover);
        on(this.root, 'click', '.location', this.onclick);
    }

    onmouseover = (e, el) => {
        this.unfocus();
        el.classList.add('focus');
    }

    onclick = (e, el) => {
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

    prevnext = (next) => {
        // arrows up
        var locations = [...this.root.querySelectorAll('.location')];
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

    input = (val, source) => {
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
            this.root.append(c3nav._build_location_html(matches[i][0]));
        }
    }
}

class LocationDetails {
    root;
    detailsBody;
    editor;
    reportIssue;
    reportMissing;

    id = null;

    constructor(root) {
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

    setLoading = (loading) => {
        this.root.classList.toggle('loading', loading);
    }

    setError = (error) => {
        this.detailsBody.textContent = `Error ${error}`;
        this.editor.classList.add('hidden');
        this.report.classList.add('hidden');
        this.setLoading(false);
    }

    setLocation = (location) => {
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
    root;
    report;
    body;

    constructor(root) {
        this.root = root;
        this.report = root.querySelector('.report');
        this.body = root.querySelector('.details-body');

        on(root, 'click', '.close', this.close);
    }

    setIssueUrl(url) {
        this.report.href = url;
    }


    setLoading = (loading) => {
        this.root.classList.toggle('loading', loading);
    }

    setRoute(route) {
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
    sidebar;
    fields;

    constructor(root, sidebar) {
        this.root = root;
        this.sidebar = sidebar;
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

        this.origin = new LocationInput(root.querySelector('#origin-input'), this);
        this.destination = new LocationInput(root.querySelector('#destination-input'), this);
        this.autocomplete = new AutoComplete(root.querySelector('#autocomplete'), this);
        this.locationDetails = new LocationDetails(root.querySelector('#location-details'), this);
        this.routeDetails = new RouteDetails(root.querySelector('#route-details'));
        this.routeOptions = new RouteOptions(root.querySelector('#route-options'), this);


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
                    const data = doc.querySelector('[data-user-data]')?.dataset?.userData ?? null;
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
        const had_sidebar = this.sidebar;
        const changed = this.assign(new_state);
        if (!replace && !changed) return;

        const url = this.build_url(c3nav.embed);
        const embed_link = document.querySelector('.embed-link');
        if (embed_link) {
            embed_link.href = this.build_url();
        }

        if (replace || (!this.sidebar && !had_sidebar)) {
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

class Map {
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


    anywherePopup = null;

    constructor(root) {
        this.root = root;
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
            var layerGroup = this.levelControl.addLevel(level[0], level[1]);
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

        // setup grid control
        if (this.root.dataset.hasOwnProperty('grid')) {
            c3nav._gridLayer = new L.SquareGridLayer(JSON.parse(this.root.dataset.grid));
            c3nav._gridControl = new SquareGridControl().addTo(this.map);
        }

        // setup user location control
        c3nav._userLocationControl = new UserLocationControl().addTo(this.map);

        L.control.zoom({
            position: 'bottomright'
        }).addTo(this.map);


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
            const data = await c3nav.json_get(`/api/locations/${name}/`);
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

    add_location = (location, icon, no_geometry) => {
        if (!location) {
            // if location is not in the searchable list...
            return;
        }
        if (location.dynamic) {
            if (!('available' in location)) {
                c3nav.json_get(`/api/locations/dynamic/${location.id}/`)
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
            c3nav.json_get(`/api/locations/${location.id}/geometry/`)
                .then(c3nav._location_geometry_loaded)
        }

        if (!location.point) return;

        const point = c3nav._location_point_overrides[location.id] || location.point.slice(1);
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
}


const LabelControl = L.Control.extend({
    options: {
        position: 'bottomright',
        addClasses: ''
    },

    onAdd: function () {
        this._container = L.DomUtil.create('div', 'leaflet-control-labels leaflet-bar ' + this.options.addClasses);
        this._button = L.DomUtil.create('a', 'material-icons', this._container);
        $(this._button).click(this.toggleLabels).dblclick(function (e) {
            e.stopPropagation();
        });
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
        return L.tileLayer(`${c3nav.tile_server || '/map/'}${id}/{z}/{x}/{y}.png`, {
            minZoom: -2,
            maxZoom: 5,
            bounds: L.GeoJSON.coordsToLatLngs(c3nav.map.bounds)
        });
    },
    addLevel: function (id, title) {
        this._tileLayers[id] = this.createTileLayer(id);
        var overlay = L.layerGroup();
        this._overlayLayers[id] = overlay;

        var link = L.DomUtil.create('a', '', this._container);
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
        var buttons = $(this._container).find('a');
        buttons.addClass('current');
        buttons.width(buttons.width());
        buttons.removeClass('current');
    },

    reloadMap: function () {
        var old_tile_layer = this._tileLayers[this.currentLevel],
            new_tile_layer = this.createTileLayer(this.currentLevel);
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
        $(this._button).click(this.toggleGrid).dblclick(function (e) {
            e.stopPropagation();
        });
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
        var i, elem, label;
        for (i = 0; i < this.config.cols.length; i++) {
            elem = L.DomUtil.create('div', 'c3nav-grid-column');
            label = String.fromCharCode(65 + (this.config.invert_x ? (this.config.cols.length - i - 2) : i));
            if (i < this.config.cols.length - 1) {
                elem.innerHTML = '<span>' + label + '</span><span>' + label + '</span>';
            }
            this._container.appendChild(elem);
            this.cols.push(elem);
        }
        for (i = 0; i < this.config.rows.length; i++) {
            elem = L.DomUtil.create('div', 'c3nav-grid-row');
            label = (this.config.invert_y ? (this.config.rows.length - i) : i);
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
        var mapSize = this._map.getSize(),
            panePos = this._map._getMapPanePos(),
            sidebarStart = $('#sidebar').outerWidth() + 15,
            searchHeight = $('#search').outerHeight() + 10,
            controlsWidth = $('.leaflet-control-zoom').outerWidth() + 10,
            attributionStart = mapSize.x - $('.leaflet-control-attribution').outerWidth() - 16,
            bottomRightStart = mapSize.y - $('.leaflet-bottom.leaflet-right').outerHeight() - 24,
            coord = null, lastCoord = null, size, center;
        this._container.style.width = mapSize.x + 'px';
        this._container.style.height = mapSize.y + 'px';
        this._container.style.left = (-panePos.x) + 'px';
        this._container.style.top = (-panePos.y) + 'px';
        for (i = 0; i < this.config.cols.length; i++) {
            coord = this._map.latLngToContainerPoint([0, this.config.cols[i]], this._map.getZoom()).x;
            coord = Math.min(mapSize.x, Math.max(-1, coord));
            this.cols[i].style.left = coord + 'px';
            if (i > 0) {
                size = coord - lastCoord;
                center = (lastCoord + coord) / 2;
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
        for (i = 0; i < this.config.rows.length; i++) {
            coord = this._map.latLngToContainerPoint([this.config.rows[i], 0], this._map.getZoom()).y;
            coord = Math.min(mapSize.y, Math.max(-1, coord));
            this.rows[i].style.top = coord + 'px';
            if (i > 0) {
                size = lastCoord - coord;
                center = (lastCoord + coord) / 2;
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


window.fake_location = () => {
    return c3nav.json_get('/api/routing/locate_test/').then(data => data.location);
}