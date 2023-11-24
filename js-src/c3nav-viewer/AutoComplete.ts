import { OriginInput } from "./OriginInput";

export class AutoComplete {
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