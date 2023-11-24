export class State {
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