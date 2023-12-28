from django.utils.functional import Promise

from c3nav.api.schema import APIErrorSchema


class CustomAPIException(Exception):
    status_code = 400
    detail = ""

    def __init__(self, detail=None):
        if detail is not None:
            if isinstance(detail, Promise):
                self.detail = str(detail)
            else:
                self.detail = detail

    def get_response(self, api, request):
        return api.create_response(request, {"detail": self.detail}, status=self.status_code)

    @classmethod
    def dict(cls):
        return {cls.status_code: APIErrorSchema}


class APIUnauthorized(CustomAPIException):
    status_code = 401
    detail = "Authorization is required for this endpoint."


class APIKeyInvalid(CustomAPIException):
    status_code = 401
    detail = "Invalid API key."


class APIPermissionDenied(CustomAPIException):
    status_code = 403
    detail = "Permission denied."


class API404(CustomAPIException):
    status_code = 404
    detail = "Object not found."


class APIConflict(CustomAPIException):
    status_code = 409
    detail = "Conflict"


class APIRequestValidationFailed(CustomAPIException):
    status_code = 422
    detail = "Bad request body."


class APIRequestDontUseAPIKey(CustomAPIException):
    status_code = 422
    detail = "The endpoint needs to be used without an API key"
