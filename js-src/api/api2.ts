import {Client, GetFetchOptions, GetPaths} from "./fetch-client.js";
import {paths} from "./v2.js";
import {HasRequiredKeys} from "openapi-typescript-helpers";

export class Api2 {
    private client: Client<paths>;
    private api_token: string;
    private auth_promise = null;

    constructor(baseUrl: string) {
        this.client = new Client<paths>({
            baseUrl: baseUrl,
            apiKey: () => this.api_token,
        });
    }

    private async get<P extends GetPaths<paths>>(path: P, ...init: HasRequiredKeys<GetFetchOptions<paths, P>> extends never
        ? [GetFetchOptions<paths, P>?]
        : [GetFetchOptions<paths, P>]) {
        const result = await this.client.GET(path, ...init);
        if (result.response.ok) {
            return result.data;
        } else {
            throw result.error;
        }
    }

    public async authenticate_session() {
        this.auth_promise = this.get("/api/v2/auth/session/", {});
        const {token} = await this.auth_promise;
        this.api_token = token;
        return token;
    }

    public async session_authenticated() {
        if (this.auth_promise === null) {
            await this.authenticate_session();
        } else {
            await this.auth_promise;
        }
    }
}