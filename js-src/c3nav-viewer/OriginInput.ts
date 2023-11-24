import {SlimLocation} from "../api";

export class OriginInput {
    root: HTMLElement;
    icon: HTMLElement;
    inputEl: HTMLInputElement;
    subtitle: HTMLElement;
    locateButton: HTMLElement;
    clearButton: HTMLElement;
    location: SlimLocation = null;
    lastlocation: SlimLocation = null;
    suggestion: SlimLocation = null;
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

    set = (location: SlimLocation) => {
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
            this.icon.textContent = c3nav_icon((location.icon as string) ?? 'place');
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