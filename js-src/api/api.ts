import {AuthApi, MapApi, MapdataApi, MeshApi} from "./apis";
import {BASE_PATH, Configuration, FetchParams, RequestContext} from "./runtime";


export class Api {
    private _token = '';
    public readonly map: MapApi;
    public readonly mapdata: MapdataApi;
    public readonly mesh: MeshApi;
    public readonly auth: AuthApi;

    constructor(private readonly base: string = BASE_PATH) {
        this.auth = new AuthApi(new Configuration({
            basePath: this.base,
            credentials: 'include'
        }));

        const config = new Configuration({
            basePath: this.base,
            apiKey: () => this._token,
        })

        this.map = new MapApi(config);
        this.mapdata = new MapdataApi(config);
        this.mesh = new MeshApi(config);
    }

    public async authorize_session(): Promise<string> {
        const {token} = await this.auth.authSessionToken();
        this._token = token;
        return token;
    }

    get token(): string {
        return this._token;
    }

    set token(value: string) {
        this._token = value;
    }

}