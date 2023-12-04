from ninja import NinjaAPI, Redoc, Swagger
from ninja.openapi.docs import DocsBase
from ninja.operation import Operation
from ninja.schema import NinjaGenerateJsonSchema

from c3nav.api.auth import APITokenAuth
from c3nav.api.exceptions import CustomAPIException


class c3navAPI(NinjaAPI):
    def get_openapi_operation_id(self, operation: Operation) -> str:
        name = operation.view_func.__name__
        result = f"c3nav_{operation.tags[0]}_{name}"
        return result


class SwaggerAndRedoc(DocsBase):
    swagger_config = Swagger(settings={
        "persistAuthorization": True,
        "defaultModelRendering": "model",
    })
    redoc_config = Redoc(settings={
        "hideOneOfDescription": True,
        "expandSingleSchemaField": True,
        "jsonSampleExpandLevel": 5,
        "expandResponses": "200",
        "hideSingleRequestSampleTab": True,
        "nativeScrollbars": True,
        "simpleOneOfTypeLabel": True,
    })

    def render_page(self, request, api):
        print(request.GET)
        if request.GET.get('swagger', None) is not None:
            return self.swagger_config.render_page(request, api)
        return self.redoc_config.render_page(request, api)


description = """

Nearly all endpoints require authentication, but guest authentication can be used.

API endpoints may change to add more features and properties, but we will attempt to keep it backwards-compatible.

We provide two API documentation viewers:

* [Redoc](/api/v2/): more comprehensive and clean *(default)*
* [Swagger](/api/v2/?swagger): less good, but has a built-in API client

We recommend reading the documentation using Redoc, and either using the Code examples provided next to each request,
or switching to swagger if you want an in-browser API client. 


""".strip()
ninja_api = c3navAPI(
    title="c3nav API",
    version="v2",
    description=description,

    docs_url="/",
    docs=SwaggerAndRedoc(),

    auth=APITokenAuth(),

    openapi_extra={
        "tags": [
            {
                "name": "auth",
                "x-displayName": "Authentication",
                "description": "Get and manage API access",
            },
            {
                "name": "updates",
                "x-displayName": "Updates",
                "description": "Get regular updates",
            },
            {
                "name": "map",
                "x-displayName": "Map",
                "description": "Common map endpoints",
            },
            {
                "name": "routing",
                "x-displayName": "Routing",
                "description": "Calculate routes",
            },
            {
                "name": "positioning",
                "x-displayName": "Positioning",
                "description": "Determine your position",
            },
            {
                "name": "mapdata-root",
                "x-displayName": "Root map data",
                "description": "Objects that don't belong to a level or space",
            },
            {
                "name": "mapdata-level",
                "x-displayName": "Level map data",
                "description": "Objects that belong to a level",
            },
            {
                "name": "mapdata-space",
                "x-displayName": "Space map data",
                "description": "Objects that belong to a space",
            },
            {
                "name": "editor",
                "x-displayName": "Editor",
                "description": "Endpoints for the editor and to interface with the editor",
            },
            {
                "name": "mesh",
                "x-displayName": "Mesh",
                "description": "Manage the location node mesh network",
            },
        ],
        "x-tagGroups": [
            {
                "name": "Setup",
                "tags": ["auth", "updates"],
            },
            {
                "name": "Main",
                "tags": ["map", "routing", "positioning"],
            },
            {
                "name": "Raw map data",
                "tags": ["mapdata-root", "mapdata-level", "mapdata-space"],
            },
            {
                "name": "Other",
                "tags": ["editor", "mesh"],
            },

        ]
    }
)


"""
ugly hack: remove schema from the end of definition names
"""
orig_normalize_name = NinjaGenerateJsonSchema.normalize_name
def wrap_normalize_name(self, name: str):  # noqa
    return orig_normalize_name(self, name).removesuffix('Schema')
NinjaGenerateJsonSchema.normalize_name = wrap_normalize_name  # noqa


@ninja_api.exception_handler(CustomAPIException)
def on_invalid_token(request, exc):
    return ninja_api.create_response(request, {"detail": exc.detail}, status=exc.status_code)
