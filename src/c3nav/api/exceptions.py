class CustomAPIException(Exception):
    status_code = 400
    detail = ""

    def __init__(self, detail=None):
        if detail is not None:
            self.detail = detail

    def get_response(self, api, request):
        return api.create_response(request, {"detail": self.detail}, status=self.status_code)


class API404(CustomAPIException):
    status_code = 404
    detail = "Object not found."


class APIUnauthorized(CustomAPIException):
    status_code = 401
    detail = "Authorization is required for this endpoint."


class APITokenInvalid(CustomAPIException):
    status_code = 401
    detail = "Invalid API token."


class APIPermissionDenied(CustomAPIException):
    status_code = 403
    detail = "Permission denied."

