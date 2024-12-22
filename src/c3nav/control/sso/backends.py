from social_core.backends.open_id_connect import OpenIdConnectAuth
from social_core.backends.keycloak import KeycloakOAuth2


class EurofurenceIdentityOpenId(OpenIdConnectAuth):
    """Eurofurence Identity OpenID authentication backend"""
    name = 'eurofurence-identity'
    OIDC_ENDPOINT = 'https://identity.eurofurence.org/'
    DEFAULT_SCOPE = ['openid', 'profile', 'groups']
    EXTRA_DATA = ["id_token", "refresh_token", ("sub", "id"), "groups"]
    TOKEN_ENDPOINT_AUTH_METHOD = 'client_secret_post'
    USERNAME_KEY = "name"


class CCCHHOAuth2(KeycloakOAuth2):
    """CCCHH ID"""
    name = 'ccchh'
    verbose_name = 'CCCHH ID'

    def get_user_details(self, response):
        """Map fields in user_data into Django User fields"""
        return {
            "username": response.get("preferred_username"),
            "fullname": response.get("name", ''),
            "first_name": response.get("given_name", ''),
            "last_name": response.get("family_name", ''),
        }


class C3VOCOpenID(OpenIdConnectAuth):
    """C3VOC SSO"""
    name = 'c3voc'
    verbose_name = 'C3VOC SSO'
    DEFAULT_SCOPE = ['openid', 'profile', 'groups']
    EXTRA_DATA = ["id_token", "refresh_token", ("sub", "id"), "groups"]


class C3NOCOpenID(OpenIdConnectAuth):
    """C3NOC SSO"""
    name = 'c3noc'
    verbose_name = 'C3NOC SSO'
    DEFAULT_SCOPE = ['openid', 'profile', 'groups']
    EXTRA_DATA = ["id_token", "refresh_token", ("sub", "id"), "groups"]
