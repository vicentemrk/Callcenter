import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured

import environ

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIRS = os.path.join(BASE_DIR,'templates')

# Carga el archivo .env del proyecto con django-environ.
# read_env no sobreescribe variables que ya existan en el entorno del sistema,
# por lo que en produccion las variables reales siempre tienen prioridad.
environ.Env.read_env(os.path.join(BASE_DIR, '.env'))

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.1/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
DEBUG = os.environ.get('DJANGO_DEBUG', 'True').lower() in ('1', 'true', 'yes')
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'insecure-development-key-change-before-deploying')
if not DEBUG and SECRET_KEY == 'insecure-development-key-change-before-deploying':
    raise ImproperlyConfigured('Set DJANGO_SECRET_KEY when DJANGO_DEBUG is disabled.')

# SECURITY WARNING: don't run with debug turned on in production!
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get(
        'DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1'
    ).split(',')
    if host.strip()
]


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'administracion',
    'online',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'CallCenterGamer.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [TEMPLATES_DIRS],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'CallCenterGamer.wsgi.application'


# Database
# https://docs.djangoproject.com/en/4.1/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3', 
        'NAME': os.environ.get('DB_NAME', str(BASE_DIR / 'db.sqlite3')),
    }
}
if not DEBUG:
    missing_database_settings = [
        setting
        for setting in ('DB_NAME', 'DB_USER', 'DB_PASSWORD', 'DB_HOST')
        if not os.environ.get(setting)
    ]
    if missing_database_settings:
        raise ImproperlyConfigured(
            'Set these database environment variables when DJANGO_DEBUG is disabled: '
            + ', '.join(missing_database_settings)
        )
        


# Password validation
# https://docs.djangoproject.com/en/4.1/ref/settings/#auth-password-validators

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


# Internationalization
# https://docs.djangoproject.com/en/4.1/topics/i18n/

LANGUAGE_CODE = 'es-ES'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.1/howto/static-files/

STATIC_URL = 'static/'

# Default primary key field type
# https://docs.djangoproject.com/en/4.1/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTH_USER_MODEL = 'online.Usuario'
LOGIN_URL = 'Login'
LOGIN_REDIRECT_URL = 'index'
LOGOUT_REDIRECT_URL = 'Login'

# Configuraciones adicionales para desarrollo
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')

# ---------------------------------------------------------------------------
# Configuracion del asistente de IA (Groq remoto).
# Todo se puede sobreescribir desde el .env o desde el entorno del sistema.
# ---------------------------------------------------------------------------
IA_API_KEY = os.environ.get('IA_API_KEY', '') or os.environ.get('OPENAI_API_KEY', '')
IA_BASE_URL = os.environ.get('IA_BASE_URL', 'https://api.groq.com/openai/v1').strip()
IA_MODEL = os.environ.get('IA_MODEL', 'openai/gpt-oss-20b').strip()
IA_TIMEOUT = float(os.environ.get('IA_TIMEOUT', '15'))
IA_MAX_TOKENS = int(os.environ.get('IA_MAX_TOKENS', '400'))

# Logging: los mensajes se muestran en consola y se guardan en este archivo.
LOG_DIR = BASE_DIR / 'logs'
LOG_FILE = LOG_DIR / 'callcentergamer.log'
LOG_DIR.mkdir(exist_ok=True)

"""
Configuracion del sistema de logging:
LOGGING:
    Es el diccionario principal que Django utiliza para saber como manejar
    los mensajes del sistema.
version:
    Indica la version del formato de configuracion que utiliza Python.

disable_existing_loggers:
    En False, permite conservar los loggers que Django ya trae configurados. 
formatters:
    Define el formato visible de cada registro.
format:
    Define el contenido de cada linea del log:
    - asctime: fecha y hora del registro.
    - levelname: nivel del mensaje, por ejemplo INFO o ERROR.
    - name: archivo o modulo que genero el mensaje.
    - message: explicacion del evento ocurrido.
style:
    Indica que el formato utiliza llaves, como {asctime} y {message}.
handlers:
    Indica hacia donde se enviaran los registros.
archivo:
    Guarda los mensajes en un archivo.
class:
    Indica la herramienta de Python que se utilizara para enviar el registro.
    StreamHandler escribe en consola y FileHandler escribe en un archivo.
encoding:
    Permite guardar correctamente caracteres como tildes y la letra ñ.
loggers:
    Define que partes del proyecto pueden generar registros.
handlers:
    Indica que cada mensaje se mostrara en consola y se guardara en archivo.
level:
    INFO permite guardar mensajes INFO, WARNING, ERROR y CRITICAL.|
propagate:
    En False evita que el mismo mensaje se duplique en otros loggers de Django.
"""

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'formato_simple': {
            'format': '{asctime} [{levelname}] {name}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'formato_simple',
        },
        'archivo': {
            'class': 'logging.FileHandler',
            'filename': LOG_FILE,
            'formatter': 'formato_simple',
            'encoding': 'utf-8',
        },
    },
    'loggers': {
        'online': {
            'handlers': ['console', 'archivo'],
            'level': 'INFO',
            'propagate': False,
        },
        'administracion': {
            'handlers': ['console', 'archivo'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}