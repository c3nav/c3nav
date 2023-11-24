export class Settings {
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