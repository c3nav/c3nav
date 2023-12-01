from ninja import NinjaAPI, Swagger
from ninja.operation import Operation
from ninja.schema import NinjaGenerateJsonSchema

from c3nav.api.exceptions import CustomAPIException
from c3nav.api.newauth import APITokenAuth


class c3navAPI(NinjaAPI):
    def get_openapi_operation_id(self, operation: Operation) -> str:
        name = operation.view_func.__name__
        result = f"c3nav_{operation.tags[0]}_{name}"
        return result


description = """
Nearly all endpoints require authentication, but guest authentication can be used.

API endpoints may change to add more features and properties,
but no properties will be removed without a version change.
""".strip()
ninja_api = c3navAPI(
    title="c3nav API",
    version="v2",
    description=description,

    docs_url="/",
    docs=Swagger(settings={
        "persistAuthorization": True,
        "defaultModelRendering": "model",
    }),

    auth=APITokenAuth(),

    openapi_extra={
        "tags": [
            {
                "name": "auth",
                "description": "Get and manage API access",
            },
            {
                "name": "map",
                "description": "Common map endpoints",
            },
            {
                "name": "routing",
                "description": "Calculate routes",
            },
            {
                "name": "positioning",
                "description": "Determine your position",
            },
            {
                "name": "mapdata",
                "description": "Access the raw map data",
            },
            {
                "name": "editor",
                "description": "Endpoints for the editor and to interface with the editor",
            },
            {
                "name": "mesh",
                "description": "Manage the location node mesh network",
            },
        ],
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
