(function () {

    class C3NavApi {
        key = 'anonymous';

        constructor(base ) {
            this.base = base;
            this.auth_promise = fetch(this.base+'auth/session/', {
                credentials: 'include',
                method: 'GET',
            })
                .then(res => res.json())
                .then(data => {
                    this.key = data.key
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
                credentials: 'include',
                method: 'GET',
                headers: {
                    'X-API-Key': this.key,
                    'Accept': 'application/json'
                }
            })
                .then(res => res.json())
        }

        post(path, data) {
            return fetch(this.make_url(path), {
                credentials: 'include',
                method: 'POST',
                headers: {
                    'X-API-Key': this.key,
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
