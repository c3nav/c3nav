from social_core.backends.open_id_connect import OpenIdConnectAuth


class EurofurenceIdentityOpenId(OpenIdConnectAuth):
    """Eurofurence Identity OpenID authentication backend"""
    name = 'eurofurence-identity'
    OIDC_ENDPOINT = 'https://identity.eurofurence.org/'
    DEFAULT_SCOPE = ['openid', 'profile', 'groups']
    EXTRA_DATA = ["id_token", "refresh_token", ("sub", "id"), "groups"]
    TOKEN_ENDPOINT_AUTH_METHOD = 'client_secret_post'
    USERNAME_KEY = "name"
