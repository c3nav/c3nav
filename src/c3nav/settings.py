# c3nav settings, mostly taken from the pretix project
import configparser
import os
import string
import sys
from contextlib import suppress
from pathlib import Path

import sass
from django.contrib.messages import constants as messages
from django.utils.crypto import get_random_string
from django.utils.translation import gettext_lazy as _

config = configparser.RawConfigParser()
if 'C3NAV_CONFIG' in os.environ:
    open(os.environ.get('C3NAV_CONFIG'), encoding='utf-8')
config.read(['/etc/c3nav/c3nav.cfg', os.path.expanduser('~/.c3nav.cfg'), os.environ.get('C3NAV_CONFIG', 'c3nav.cfg')],
            encoding='utf-8')

INSTANCE_NAME = config.get('c3nav', 'name', fallback='')

SENTRY_DSN = config.get('sentry', 'dsn', fallback=None)

with suppress(ImportError):
    if SENTRY_DSN:
        import sentry_sdk
        from sentry_sdk.integrations.celery import CeleryIntegration
        from sentry_sdk.integrations.django import DjangoIntegration

        sentry_sdk.init(
            dsn=SENTRY_DSN,
            integrations=[CeleryIntegration(), DjangoIntegration()]
        )

# Build paths inside the project like this: BASE_DIR / 'something'
PROJECT_DIR = Path(__file__).resolve().parent
BASE_DIR = PROJECT_DIR.parent
DATA_DIR = config.get('c3nav', 'datadir', fallback=os.environ.get('C3NAV_DATA_DIR', None))
DATA_DIR = Path(DATA_DIR).resolve() if DATA_DIR else BASE_DIR / 'data'
LOG_DIR = config.get('c3nav', 'logdir', fallback=None)
LOG_DIR = Path(LOG_DIR).resolve() if LOG_DIR else DATA_DIR / 'logs'
MEDIA_ROOT = DATA_DIR / 'media'
SOURCES_ROOT = DATA_DIR / 'sources'
MAP_ROOT = DATA_DIR / 'map'
RENDER_ROOT = DATA_DIR / 'render'
TILES_ROOT = DATA_DIR / 'tiles'
CACHE_ROOT = DATA_DIR / 'cache'
STATS_ROOT = DATA_DIR / 'stats'

if not DATA_DIR.exists():
    DATA_DIR.mkdir(parents=True)
for subdir in (LOG_DIR, MEDIA_ROOT, SOURCES_ROOT, MAP_ROOT, RENDER_ROOT, TILES_ROOT, CACHE_ROOT, STATS_ROOT):
    if not subdir.exists():
        subdir.mkdir()

MEDIA_URL = '/media/'

PUBLIC_EDITOR = config.getboolean('c3nav', 'editor', fallback=True)
PUBLIC_BASE_MAPDATA = config.getboolean('c3nav', 'public_base_mapdata', fallback=False)
AUTO_PROCESS_UPDATES = config.getboolean('c3nav', 'auto_process_updates', fallback=True)

RANDOM_LOCATION_GROUPS = config.get('c3nav', 'random_location_groups', fallback=None)
if RANDOM_LOCATION_GROUPS:
    RANDOM_LOCATION_GROUPS = tuple(int(i) for i in RANDOM_LOCATION_GROUPS.split(','))

if config.has_option('django', 'secret'):
    SECRET_KEY = config.get('django', 'secret')
else:
    SECRET_FILE = DATA_DIR / '.secret'
    if SECRET_FILE.exists():
        with open(SECRET_FILE, 'r') as f:
            SECRET_KEY = f.read().strip()
    else:
        SECRET_KEY = get_random_string(50, string.printable)
        with open(SECRET_FILE, 'w') as f:
            os.chmod(SECRET_FILE, 0o600)
            os.chown(SECRET_FILE, os.getuid(), os.getgid())
            f.write(SECRET_KEY)

if config.has_option('c3nav', 'tile_secret'):
    SECRET_TILE_KEY = config.get('c3nav', 'tile_secret')
else:
    SECRET_TILE_FILE = DATA_DIR / '.tile_secret'
    if SECRET_TILE_FILE.exists():
        with open(SECRET_TILE_FILE, 'r') as f:
            SECRET_TILE_KEY = f.read().strip()
    else:
        SECRET_TILE_KEY = get_random_string(50, string.printable)
        with open(SECRET_TILE_FILE, 'w') as f:
            os.chmod(SECRET_TILE_FILE, 0o600)
            os.chown(SECRET_TILE_FILE, os.getuid(), os.getgid())
            f.write(SECRET_TILE_KEY)

# Adjustable settings

debug_fallback = "runserver" in sys.argv
DEBUG = config.getboolean('django', 'debug', fallback=debug_fallback)

RENDER_SCALE = float(config.get('c3nav', 'render_scale', fallback=20.0))
IMAGE_RENDERER = config.get('c3nav', 'image_renderer', fallback='svg')
SVG_RENDERER = config.get('c3nav', 'svg_renderer', fallback='rsvg-convert')

CACHE_TILES = config.getboolean('c3nav', 'cache_tiles', fallback=not DEBUG)
CACHE_RESOLUTION = config.getint('c3nav', 'cache_resolution', fallback=4)

IMPRINT_ADDRESS = config.get('c3nav', 'imprint_address', fallback=None)
IMPRINT_PATRONS = config.get('c3nav', 'imprint_patrons', fallback=None)
IMPRINT_TEAM = config.get('c3nav', 'imprint_team', fallback=None)
IMPRINT_HOSTING = config.get('c3nav', 'imprint_hosting', fallback=None)

INITIAL_LEVEL = config.get('c3nav', 'initial_level', fallback=None)
INITIAL_BOUNDS = config.get('c3nav', 'initial_bounds', fallback='').split(' ')

GRID_ROWS = config.get('c3nav', 'grid_rows', fallback=None)
GRID_COLS = config.get('c3nav', 'grid_cols', fallback=None)

if len(INITIAL_BOUNDS) == 4:
    try:
        INITIAL_BOUNDS = tuple(float(i) for i in INITIAL_BOUNDS)
    except ValueError:
        INITIAL_BOUNDS = None
else:
    INITIAL_BOUNDS = None

db_backend = config.get('database', 'backend', fallback='sqlite3')
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.' + db_backend,
        'NAME': config.get('database', 'name', fallback=DATA_DIR / 'db.sqlite3'),
        'USER': config.get('database', 'user', fallback=''),
        'PASSWORD': config.get('database', 'password', fallback=''),
        'HOST': config.get('database', 'host', fallback=''),
        'PORT': config.get('database', 'port', fallback=''),
        'CONN_MAX_AGE': 0 if db_backend == 'sqlite3' else 120
    }
}
DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'

STATIC_URL = config.get('urls', 'static', fallback='/static/')

ALLOWED_HOSTS = [n for n in config.get('django', 'hosts', fallback='').split(',') if n]

LANGUAGE_CODE = config.get('locale', 'default', fallback='en')
TIME_ZONE = config.get('locale', 'timezone', fallback='UTC')

MAIL_FROM = SERVER_EMAIL = DEFAULT_FROM_EMAIL = config.get('mail', 'from', fallback='c3nav@localhost')
EMAIL_HOST = config.get('mail', 'host', fallback='localhost')
EMAIL_PORT = config.getint('mail', 'port', fallback=25)
EMAIL_HOST_USER = config.get('mail', 'user', fallback='')
EMAIL_HOST_PASSWORD = config.get('mail', 'password', fallback='')
EMAIL_USE_TLS = config.getboolean('mail', 'tls', fallback=False)
EMAIL_USE_SSL = config.getboolean('mail', 'ssl', fallback=False)
EMAIL_SUBJECT_PREFIX = ('[c3nav-%s] ' % INSTANCE_NAME) if INSTANCE_NAME else '[c3nav]'

ADMINS = [('Admin', n) for n in config.get('mail', 'admins', fallback='').split(",") if n]

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'unique-snowflake',
    }
}
HAS_REAL_CACHE = False

SESSION_ENGINE = "django.contrib.sessions.backends.db"

HAS_MEMCACHED = config.has_option('memcached', 'location')
if HAS_MEMCACHED:
    HAS_REAL_CACHE = True
    CACHES['default'] = {
        'BACKEND': 'django.core.cache.backends.memcached.PyLibMCCache',
        'LOCATION': config.get('memcached', 'location'),
    }
    SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"

HAS_REDIS = config.has_option('redis', 'location')
if HAS_REDIS:
    HAS_REAL_CACHE = True
    CACHES['redis'] = {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": config.get('redis', 'location'),
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        }
    }
    if not HAS_MEMCACHED:
        CACHES['default'] = CACHES['redis']
        SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"
    else:
        SESSION_CACHE_ALIAS = "redis"

HAS_CELERY = config.has_option('celery', 'broker')
if HAS_CELERY:
    BROKER_URL = config.get('celery', 'broker')
    CELERY_RESULT_BACKEND = config.get('celery', 'backend')
    CELERY_SEND_TASK_ERROR_EMAILS = bool(ADMINS)
else:
    CELERY_ALWAYS_EAGER = True
CELERY_TASK_SERIALIZER = 'json'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_RESULT_SERIALIZER = 'json'

TILE_CACHE_SERVER = config.get('c3nav', 'tile_cache_server', fallback=None)

# Internal settings
STATIC_ROOT = PROJECT_DIR / 'static.dist'

SESSION_COOKIE_NAME = 'c3nav_session'
SESSION_COOKIE_DOMAIN = config.get('c3nav', 'session_cookie_domain', fallback=None)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG

LANGUAGE_COOKIE_NAME = 'c3nav_language'

CSRF_COOKIE_NAME = 'c3nav_csrftoken'
CSRF_COOKIE_SECURE = not DEBUG

TILE_ACCESS_COOKIE_NAME = 'c3nav_tile_access'
TILE_ACCESS_COOKIE_DOMAIN = config.get('c3nav', 'tile_access_cookie_domain', fallback=None)
TILE_ACCESS_COOKIE_HTTPONLY = True
TILE_ACCESS_COOKIE_SECURE = not DEBUG


# Application definition

INSTALLED_APPS = [
    "daphne",
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'channels',
    'compressor',
    'bootstrap3',
    'c3nav.api',
    'rest_framework',
    'c3nav.mapdata',
    'c3nav.routing',
    'c3nav.site',
    'c3nav.control',
    'c3nav.mesh',
    'c3nav.editor',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'c3nav.mapdata.middleware.NoLanguageMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'c3nav.mapdata.middleware.UserDataMiddleware',
    'c3nav.site.middleware.MobileclientMiddleware',
    'c3nav.control.middleware.UserPermissionsMiddleware',
    'c3nav.api.middleware.JsonRequestBodyMiddleware',
]

with suppress(ImportError):
    import debug_toolbar  # noqa
    INSTALLED_APPS.append('debug_toolbar')
    MIDDLEWARE.append('debug_toolbar.middleware.DebugToolbarMiddleware')

with suppress(ImportError):
    import htmlmin  # noqa
    MIDDLEWARE += [
        'htmlmin.middleware.HtmlMinifyMiddleware',
        'htmlmin.middleware.MarkRequestMiddleware',
    ]

with suppress(ImportError):
    import django_extensions  # noqa
    INSTALLED_APPS.append('django_extensions')

# Security settings
X_FRAME_OPTIONS = 'DENY'

# URL settings
ROOT_URLCONF = 'c3nav.urls'

WSGI_APPLICATION = 'c3nav.wsgi.application'
ASGI_APPLICATION = 'c3nav.asgi.application'

if HAS_REDIS:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {
                "hosts": [config.get('redis', 'location')],
            },
        },
    }
else:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer"
        }
    }

USE_I18N = True
USE_L10N = True
USE_TZ = True

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework.authentication.SessionAuthentication',
        'c3nav.api.auth.APISecretAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.AllowAny',
    )
}

LOCALE_PATHS = (
    PROJECT_DIR / 'locale',
)

LANGUAGES = [
    ('en', _('English')),
    ('de', _('German')),
]

template_loaders = (
    'django.template.loaders.filesystem.Loader',
    'django.template.loaders.app_directories.Loader',
)
if not DEBUG:
    template_loaders = (
        ('django.template.loaders.cached.Loader', template_loaders),
    )
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'OPTIONS': {
            'context_processors': [
                'django.contrib.auth.context_processors.auth',
                'django.template.context_processors.debug',
                'django.template.context_processors.i18n',
                'django.template.context_processors.request',
                'django.contrib.messages.context_processors.messages',
                'c3nav.site.context_processors.logos',
                'c3nav.site.context_processors.colors',
                'c3nav.site.context_processors.user_data_json',
            ],
            'loaders': template_loaders
        },
    },
]


STATICFILES_FINDERS = (
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
    'compressor.finders.CompressorFinder',
    'c3nav.site.finders.LogoFinder',
)

BOOTSTRAP3 = {
    'success_css_class': '',
}

STATICFILES_DIRS = [
    BASE_DIR / 'c3nav' / 'static',
]

COMPRESS_PRECOMPILERS = (
    ('text/x-scss', 'django_libsass.SassCompiler'),
)

COMPRESS_ENABLED = COMPRESS_OFFLINE = not debug_fallback

COMPRESS_CSS_FILTERS = (
    'compressor.filters.css_default.CssAbsoluteFilter',
    'compressor.filters.cssmin.CSSCompressorFilter',
)

HEADER_LOGO = config.get('c3nav', 'header_logo', fallback=None)
FAVICON = config.get('c3nav', 'favicon', fallback=None)
FAVICON_PACKAGE = config.get('c3nav', 'favicon_package', fallback=None)

PRIMARY_COLOR = config.get('c3nav', 'primary_color', fallback='')
HEADER_BACKGROUND_COLOR = config.get('c3nav', 'header_background_color', fallback='')
HEADER_TEXT_COLOR = config.get('c3nav', 'header_text_color', fallback='')
HEADER_TEXT_HOVER_COLOR = config.get('c3nav', 'header_text_hover_color', fallback='')
SAFARI_MASK_ICON_COLOR = config.get('c3nav', 'safari_mask_icon_color', fallback=PRIMARY_COLOR)
MSAPPLICATION_TILE_COLOR = config.get('c3nav', 'msapplication_tile_color', fallback='')

WIFI_SSIDS = [n for n in config.get('c3nav', 'wifi_ssids', fallback='').split(',') if n]

USER_REGISTRATION = config.getboolean('c3nav', 'user_registration', fallback=True)


def return_sass_color(color):
    if not color:
        return lambda: color

    if not color.startswith('#') or len(color) != 7 or any((i not in '0123456789abcdef') for i in color[1:]):
        raise ValueError('custom color is not a hex color!')

    return lambda: sass.SassColor(int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16), 1)


LIBSASS_CUSTOM_FUNCTIONS = {
    'primary_color': return_sass_color(PRIMARY_COLOR),
    'header_background_color': return_sass_color(HEADER_BACKGROUND_COLOR),
    'header_text_color': return_sass_color(HEADER_TEXT_COLOR),
    'header_text_hover_color': return_sass_color(HEADER_TEXT_HOVER_COLOR),
}

INTERNAL_IPS = ('127.0.0.1', '::1')

MESSAGE_TAGS = {
    messages.INFO: 'alert-info',
    messages.ERROR: 'alert-danger',
    messages.WARNING: 'alert-warning',
    messages.SUCCESS: 'alert-success',
}
MESSAGE_STORAGE = 'django.contrib.messages.storage.session.SessionStorage'

SILENCED_SYSTEM_CHECKS = ['debug_toolbar.W006']

loglevel = 'DEBUG' if DEBUG else 'INFO'

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'default': {
            'format': '%(levelname)s %(asctime)s %(name)s %(module)s %(message)s'
        },
    },
    'handlers': {
        'console': {
            'level': loglevel,
            'class': 'logging.StreamHandler',
            'formatter': 'default'
        },
        'file': {
            'level': loglevel,
            'class': 'logging.FileHandler',
            'filename': LOG_DIR / 'c3nav.log',
            'formatter': 'default'
        }
    },
    'loggers': {
        '': {
            'handlers': ['file', 'console'],
            'level': loglevel,
            'propagate': True,
        },
        'django.request': {
            'handlers': ['file', 'console'],
            'level': loglevel,
            'propagate': True,
        },
        'django.security': {
            'handlers': ['file', 'console'],
            'level': loglevel,
            'propagate': True,
        },
        'django.db.backends': {
            'handlers': ['file', 'console'],
            'level': 'INFO',  # Do not output all the queries
            'propagate': True,
        },
        'shapely.geos': {
            'handlers': ['file', 'console'],
            'level': 'INFO',
            'propagate': True,
        },
    },
}

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]
