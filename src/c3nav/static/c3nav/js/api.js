(function () {

    class C3NavApi {
        token = 'anonymous';

        constructor(base ) {
            this.base = base;
            this.auth_promise = fetch(this.base+'auth/session/', {
                credentials: 'same-origin',
                method: 'GET',
            })
                .then(res => res.json())
                .then(data => {
                    this.token = data.token
                })
                .catch(err => {
                    throw err;
                })
                .then(_ => null);
        }

        authenticated() {
            return this.auth_promise;
        }

        make_url(path) {
            const url = new URL(path, this.base);
            if (!url.pathname.endsWith('/')) {
                url.pathname += '/';
            }
            return url;
        }

        get(path) {
            return fetch(this.make_url(path), {
                credentials: 'omit',
                method: 'GET',
                headers: {
                    'Authorization': `Bearer ${this.token}`,
                    'Accept': 'application/json'
                }
            })
                .then(res => res.json())
        }

        async post(path, data) {
            return fetch(this.make_url(path), {
                credentials: 'omit',
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${this.token}`,
                    'Accept': 'application/json',
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(data),
            })
                .then(res => res.json())
        }
    }

    window.c3nav_api = new C3NavApi(`${window.location.origin}/api/v2/`);
})();