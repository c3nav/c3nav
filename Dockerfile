# This dockerfile creates an image with a dev environment of c3nav using sqlite as database.
# TODO: the used django version needs to be fixed to the latest of Dezember 2019

# syntax=docker/dockerfile:1
FROM ubuntu:20.04

# if not set tzdata hangs
ENV TZ=Europe/Berlin
# if not set manage.py runserver hangs
ENV PYTHONUNBUFFERED=1

# default admin user
ENV DEFAULT_SUPERUSER_NAME="admin"
ENV DEFAULT_SUPERUSER_PASSWORD="password"

# make tzdata shut up. Without this build hangs indefinitely.
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

RUN apt-get update && apt-get install -qy \
    build-essential \
    gettext \
    gfortran \
    libfreetype6-dev \
    libgeos-dev \
    libjpeg-dev \
    libmemcached-dev \
    liblapack-dev \
    libmysqlclient-dev \
    libopenblas-dev \
    libpq-dev \
    librsvg2-bin \
    pkg-config \
    python3 \
    python3-dev \
    python3-pip \
    python3-venv

# install the default python build tools
RUN pip3 install -U pip wheel setuptools

# create the default work dir for the app and copy the source code
RUN mkdir /app
COPY src /app/

# install all python requirements
RUN cd /app \
    && pip3 install -r requirements.txt

# copy the default configuration into the container
COPY docker/c3nav-docker-dev.cfg /etc/c3nav/c3nav.cfg

# Create the database and add the default user
RUN cd /app/ \
  && python3 manage.py makemigrations \
  && python3 manage.py migrate \
  && (echo "from django.contrib.auth import get_user_model; User = get_user_model(); User.objects.create_superuser('${DEFAULT_SUPERUSER_NAME}', 'noreply@example.com', '${DEFAULT_SUPERUSER_PASSWORD}')" | python3 manage.py shell)

CMD cd /app/ && python3 manage.py runserver 0.0.0.0:8000