import type {
    ErrorResponse,
    HttpMethod,
    SuccessResponse,
    FilterKeys,
    MediaType,
    PathsWithMethod,
    ResponseObjectMap,
    OperationRequestBodyContent,
    HasRequiredKeys,
} from "openapi-typescript-helpers";

// settings & const
const DEFAULT_HEADERS = {
    "Content-Type": "application/json",
};

// Note: though "any" is considered bad practice in general, this library relies
// on "any" for type inference only it can give.  Same goes for the "{}" type.
/* eslint-disable @typescript-eslint/no-explicit-any, @typescript-eslint/ban-types */

/** options for each client instance */
interface ClientOptions extends Omit<RequestInit, "headers"> {
    /** set the common root URL for all API requests */
    baseUrl?: string;
    /** custom fetch (defaults to globalThis.fetch) */
    fetch?: typeof fetch;
    /** global querySerializer */
    querySerializer?: QuerySerializer<unknown>;
    /** global bodySerializer */
    bodySerializer?: BodySerializer<unknown>;
    // headers override to make typing friendlier
    headers?: HeadersOptions;
    // api key
    apiKey?: string | (()=>string);
}

export type HeadersOptions =
    | HeadersInit
    | Record<string, string | number | boolean | null | undefined>;

export type QuerySerializer<T> = (
    query: T extends { parameters: any }
        ? NonNullable<T["parameters"]["query"]>
        : Record<string, unknown>,
) => string;

export type BodySerializer<T> = (body: OperationRequestBodyContent<T>) => any;

export type ParseAs = "json" | "text" | "blob" | "arrayBuffer" | "stream";

export interface DefaultParamsOption {
    params?: { query?: Record<string, unknown> };
}

export type ParamsOption<T> = T extends { parameters: any }
    ? HasRequiredKeys<T["parameters"]> extends never
        ? { params?: T["parameters"] }
        : { params: T["parameters"] }
    : DefaultParamsOption;
// v7 breaking change: TODO uncomment for openapi-typescript@7 support
// : never;

export type RequestBodyOption<T> = OperationRequestBodyContent<T> extends never
    ? { body?: never }
    : undefined extends OperationRequestBodyContent<T>
        ? { body?: OperationRequestBodyContent<T> }
        : { body: OperationRequestBodyContent<T> };

export type FetchOptions<T> = RequestOptions<T> & Omit<RequestInit, "body">;

export type FetchResponse<T> =
    | {
    data: FilterKeys<SuccessResponse<ResponseObjectMap<T>>, MediaType>;
    error?: never;
    response: Response;
}
    | {
    data?: never;
    error: FilterKeys<ErrorResponse<ResponseObjectMap<T>>, MediaType>;
    response: Response;
};

export type RequestOptions<T> = ParamsOption<T> &
    RequestBodyOption<T> & {
    querySerializer?: QuerySerializer<T>;
    bodySerializer?: BodySerializer<T>;
    parseAs?: ParseAs;
    fetch?: ClientOptions["fetch"];
};


export type GetPaths<Paths extends {}> = PathsWithMethod<Paths, "get">;
export type PutPaths<Paths extends {}> = PathsWithMethod<Paths, "put">;
export type PostPaths<Paths extends {}> = PathsWithMethod<Paths, "post">;
export type DeletePaths<Paths extends {}> = PathsWithMethod<Paths, "delete">;
export type OptionsPaths<Paths extends {}> = PathsWithMethod<Paths, "options">;
export type HeadPaths<Paths extends {}> = PathsWithMethod<Paths, "head">;
export type PatchPaths<Paths extends {}> = PathsWithMethod<Paths, "patch">;
export type TracePaths<Paths extends {}> = PathsWithMethod<Paths, "trace">;


export type GetFetchOptions<Paths, P extends GetPaths<Paths>> = FetchOptions<FilterKeys<Paths[P], "get">>;
export type PutFetchOptions<Paths, P extends PutPaths<Paths>> = FetchOptions<FilterKeys<Paths[P], "put">>;
export type PostFetchOptions<Paths, P extends PostPaths<Paths>> = FetchOptions<FilterKeys<Paths[P], "post">>;
export type DeleteFetchOptions<Paths, P extends DeletePaths<Paths>> = FetchOptions<FilterKeys<Paths[P], "delete">>;
export type OptionsFetchOptions<Paths, P extends OptionsPaths<Paths>> = FetchOptions<FilterKeys<Paths[P], "options">>;
export type HeadFetchOptions<Paths, P extends HeadPaths<Paths>> = FetchOptions<FilterKeys<Paths[P], "head">>;
export type PatchFetchOptions<Paths, P extends PatchPaths<Paths>> = FetchOptions<FilterKeys<Paths[P], "patch">>;
export type TraceFetchOptions<Paths, P extends TracePaths<Paths>> = FetchOptions<FilterKeys<Paths[P], "trace">>;


type CoreFetchResponse<Paths extends {}, P extends keyof Paths, M extends HttpMethod> = Promise<FetchResponse<M extends keyof Paths[P] ? Paths[P][M] : unknown>>


export class Client<Paths extends {}> {
    private readonly options: Omit<ClientOptions, "querySerializer" | "bodySerializer" | "fetch">;
    private readonly baseFetch: typeof fetch;
    private readonly globalQuerySerializer: QuerySerializer<unknown>;
    private readonly globalBodySerializer: BodySerializer<unknown>;
    private readonly clientOptions: ClientOptions;
    private readonly apiKey: string|(()=>string);
    private baseUrl: string;

    constructor(clientOptions: ClientOptions = {}) {
        const {
            fetch: baseFetch = fetch,
            querySerializer: globalQuerySerializer,
            bodySerializer: globalBodySerializer,
            apiKey,
            ...options
        } = clientOptions;
        let baseUrl = options.baseUrl ?? "";
        if (baseUrl.endsWith("/")) {
            baseUrl = baseUrl.slice(0, -1); // remove trailing slash
        }
        this.baseUrl = baseUrl;
        this.apiKey = apiKey;
        this.options = options;
        this.baseFetch = baseFetch;
        this.globalQuerySerializer = globalQuerySerializer;
        this.globalBodySerializer = globalBodySerializer;
        this.clientOptions = clientOptions;
    }

    private async coreFetch<P extends keyof Paths, M extends HttpMethod>(
        url: P,
        fetchOptions: FetchOptions<M extends keyof Paths[P] ? Paths[P][M] : never>,
    ): CoreFetchResponse<Paths, P, M> {
        const {
            fetch = this.baseFetch,
            headers,
            body: requestBody,
            params = {},
            parseAs = "json",
            querySerializer = this.globalQuerySerializer ?? defaultQuerySerializer,
            bodySerializer = this.globalBodySerializer ?? defaultBodySerializer,
            ...init
        } = fetchOptions || {};

        // URL
        const finalURL = createFinalURL(url as string, {
            baseUrl: this.baseUrl,
            params,
            querySerializer,
        });
        const authHeaders = {};
        if (typeof this.apiKey === 'string') {
            authHeaders['Authorization'] = `Bearer ${this.apiKey}`;
        } else if (this.apiKey) {
            authHeaders['Authorization'] = `Bearer ${this.apiKey()}`;
        }
        const finalHeaders = mergeHeaders(
            DEFAULT_HEADERS,
            this.clientOptions?.headers,
            headers,
            (params as any).header,
            authHeaders,
        );

        // fetch!
        const requestInit: RequestInit = {
            redirect: "follow",
            ...this.options,
            ...init,
            headers: finalHeaders,
        };
        if (requestBody) {
            // @ts-ignore some type fuckery
            requestInit.body = bodySerializer(requestBody);
        }
        // remove `Content-Type` if serialized body is FormData; browser will correctly set Content-Type & boundary expression
        if (requestInit.body instanceof FormData) {
            finalHeaders.delete("Content-Type");
        }
        const response = await fetch(finalURL, requestInit);

        // handle empty content
        // note: we return `{}` because we want user truthy checks for `.data` or `.error` to succeed
        if (
            response.status === 204 ||
            response.headers.get("Content-Length") === "0"
        ) {
            return response.ok
                ? {data: {} as any, response: response as any}
                : {error: {} as any, response: response as any};
        }

        // parse response (falling back to .text() when necessary)
        if (response.ok) {
            let data: any; // we have to leave this empty here so that we don't consume the body
            if (parseAs !== "stream") {
                const cloned = response.clone();
                data =
                    typeof cloned[parseAs] === "function"
                        ? await cloned[parseAs]()
                        : await cloned.text();
            } else {
                // bun consumes the body when calling response.body, therefore we need to clone the response before accessing it
                data = response.clone().body;
            }
            return {data, response: response as any};
        }

        // handle errors (always parse as .json() or .text())
        let error: any = {};
        try {
            error = await response.clone().json();
        } catch {
            error = await response.clone().text();
        }
        return {error, response: response as any};
    }


    GET<P extends GetPaths<Paths>>(
        url: P,
        ...init: HasRequiredKeys<GetFetchOptions<Paths, P>> extends never
            ? [GetFetchOptions<Paths, P>?]
            : [GetFetchOptions<Paths, P>]
    ): CoreFetchResponse<Paths, P, "get"> {
        return this.coreFetch<P, "get">(url, {...init[0], method: "GET"} as any);
    }

    PUT<P extends PutPaths<Paths>>(
        url: P,
        ...init: HasRequiredKeys<PutFetchOptions<Paths, P>> extends never
            ? [PutFetchOptions<Paths, P>?]
            : [PutFetchOptions<Paths, P>]
    ): CoreFetchResponse<Paths, P, "put"> {
        return this.coreFetch<P, "put">(url, {...init[0], method: "PUT"} as any);
    }

    POST<P extends PostPaths<Paths>>(
        url: P,
        ...init: HasRequiredKeys<PostFetchOptions<Paths, P>> extends never
            ? [PostFetchOptions<Paths, P>?]
            : [PostFetchOptions<Paths, P>]
    ): CoreFetchResponse<Paths, P, "post"> {
        return this.coreFetch<P, "post">(url, {...init[0], method: "POST"} as any);
    }

    DELETE<P extends DeletePaths<Paths>>(
        url: P,
        ...init: HasRequiredKeys<DeleteFetchOptions<Paths, P>> extends never
            ? [DeleteFetchOptions<Paths, P>?]
            : [DeleteFetchOptions<Paths, P>]
    ): CoreFetchResponse<Paths, P, "delete"> {
        return this.coreFetch<P, "delete">(url, {...init[0], method: "DELETE"} as any);
    }

    OPTIONS<P extends OptionsPaths<Paths>>(
        url: P,
        ...init: HasRequiredKeys<OptionsFetchOptions<Paths, P>> extends never
            ? [OptionsFetchOptions<Paths, P>?]
            : [OptionsFetchOptions<Paths, P>]
    ): CoreFetchResponse<Paths, P, "options"> {
        return this.coreFetch<P, "options">(url, {...init[0], method: "OPTIONS"} as any);
    }

    HEAD<P extends HeadPaths<Paths>>(
        url: P,
        ...init: HasRequiredKeys<HeadFetchOptions<Paths, P>> extends never
            ? [HeadFetchOptions<Paths, P>?]
            : [HeadFetchOptions<Paths, P>]
    ): CoreFetchResponse<Paths, P, "head"> {
        return this.coreFetch<P, "head">(url, {...init[0], method: "HEAD"} as any);
    }

    PATCH<P extends PatchPaths<Paths>>(
        url: P,
        ...init: HasRequiredKeys<PatchFetchOptions<Paths, P>> extends never
            ? [PatchFetchOptions<Paths, P>?]
            : [PatchFetchOptions<Paths, P>]
    ): CoreFetchResponse<Paths, P, "patch"> {
        return this.coreFetch<P, "patch">(url, {...init[0], method: "PATCH"} as any);
    }

    TRACE<P extends TracePaths<Paths>>(
        url: P,
        ...init: HasRequiredKeys<TraceFetchOptions<Paths, P>> extends never
            ? [TraceFetchOptions<Paths, P>?]
            : [TraceFetchOptions<Paths, P>]
    ): CoreFetchResponse<Paths, P, "trace"> {
        return this.coreFetch<P, "trace">(url, {...init[0], method: "TRACE"} as any);
    }
}
// utils

/** serialize query params to string */
export function defaultQuerySerializer<T = unknown>(q: T): string {
    const search: string[] = [];
    if (q && typeof q === "object") {
        for (const [k, v] of Object.entries(q)) {
            const value = defaultQueryParamSerializer([k], v);
            if (value) {
                search.push(value);
            }
        }
    }
    return search.join("&");
}

/** serialize different query param schema types to a string */
export function defaultQueryParamSerializer<T = unknown>(
    key: string[],
    value: T,
): string | undefined {
    if (value === null || value === undefined) {
        return undefined;
    }
    if (typeof value === "string") {
        return `${deepObjectPath(key)}=${encodeURIComponent(value)}`;
    }
    if (typeof value === "number" || typeof value === "boolean") {
        return `${deepObjectPath(key)}=${String(value)}`;
    }
    if (Array.isArray(value)) {
        if (!value.length) {
            return undefined;
        }
        const nextValue: string[] = [];
        for (const item of value) {
            const next = defaultQueryParamSerializer(key, item);
            if (next !== undefined) {
                nextValue.push(next);
            }
        }
        return nextValue.join(`&`);
    }
    if (typeof value === "object") {
        if (!Object.keys(value).length) {
            return undefined;
        }
        const nextValue: string[] = [];
        for (const [k, v] of Object.entries(value)) {
            if (v !== undefined && v !== null) {
                const next = defaultQueryParamSerializer([...key, k], v);
                if (next !== undefined) {
                    nextValue.push(next);
                }
            }
        }
        return nextValue.join("&");
    }
    return encodeURIComponent(`${deepObjectPath(key)}=${String(value)}`);
}

/** flatten a node path into a deepObject string */
function deepObjectPath(path: string[]): string {
    let output = path[0]!;
    for (const k of path.slice(1)) {
        output += `[${k}]`;
    }
    return output;
}

/** serialize body object to string */
export function defaultBodySerializer<T>(body: T): string {
    return JSON.stringify(body);
}

/** Construct URL string from baseUrl and handle path and query params */
export function createFinalURL<O>(
    pathname: string,
    options: {
        baseUrl: string;
        params: { query?: Record<string, unknown>; path?: Record<string, unknown> };
        querySerializer: QuerySerializer<O>;
    },
): string {
    let finalURL = `${options.baseUrl}${pathname}`;
    if (options.params.path) {
        for (const [k, v] of Object.entries(options.params.path)) {
            finalURL = finalURL.replace(`{${k}}`, encodeURIComponent(String(v)));
        }
    }
    const search = options.querySerializer((options.params.query as any) ?? {});
    if (search) {
        finalURL += `?${search}`;
    }
    return finalURL;
}

/** merge headers a and b, with b taking priority */
export function mergeHeaders(
    ...allHeaders: (HeadersOptions | undefined)[]
): Headers {
    const headers = new Headers();
    for (const headerSet of allHeaders) {
        if (!headerSet || typeof headerSet !== "object") {
            continue;
        }
        const iterator =
            headerSet instanceof Headers
                ? headerSet.entries()
                : Object.entries(headerSet);
        for (const [k, v] of iterator) {
            if (v === null) {
                headers.delete(k);
            } else if (v !== undefined) {
                headers.set(k, v as any);
            }
        }
    }
    return headers;
}
