(function () {

    class C3NavApi {
        key = 'anonymous';

        constructor(base ) {
            this.base = base;
            this.auth_promise = this.authenticate();
        }

        authenticate() {
            this.auth_promise = fetch(this.base+'auth/session/', {
                credentials: 'same-origin',
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
            return this.auth_promise;
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

        async req(method, path, body) {
            await this.auth_promise;
            const init = {
                credentials: 'include',
                method: method,
                headers: {
                    'X-API-Key': this.key,
                    'Accept': 'application/json'
                }
            };
            if (typeof body !== 'undefined') {
                init.body = JSON.stringify(body);
            }
            const res = await fetch(this.make_url(path), init);
            return await res.json();
        }

        get(path) {
            return this.req('GET', path);
        }

        post(path, data) {
            return this.req('POST', path, data);
        }

        put(path, data) {
            return this.req('PUT', path, data);
        }
    }

    window.c3nav_api = new C3NavApi(`${window.location.origin}/api/v2/`);
})();
