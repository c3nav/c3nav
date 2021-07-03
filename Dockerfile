# This dockerfile creates an image with a dev environment of c3nav using sqlite as database.
# TODO: the used django version needs to be fixed to the latest of Dezember 2019

# syntax=docker/dockerfile:1
FROM ubuntu:20.04
EXPOSE 8000

# if not set tzdata hangs
ENV TZ=Europe/Berlin
# if not set manage.py runserver hangs
ENV PYTHONUNBUFFERED=1

# Adding application user
# To avoid problems while accessing the sqlite database from the host the user id and group id should equal your host systems user
RUN groupadd -g 1000 c3nav \
    && useradd -r -u 1000 -g c3nav c3nav \
    && mkdir -p /home/c3nav/ \
    && chown -R c3nav:c3nav /home/c3nav/

# make tzdata shut up. Without this build hangs indefinitely.
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone
RUN mkdir /etc/c3nav/ && ln -s /usr/share/c3nav/docker/c3nav-docker-dev.cfg /etc/c3nav/c3nav.cfg
RUN ln -s /usr/share/c3nav/src /app

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

# drop privileges to application user
USER c3nav

# install the default python build tools
RUN pip3 install -U pip wheel setuptools
COPY src/requirements.txt /tmp/req_temp/requirements.txt
COPY src/requirements/ /tmp/req_temp/requirements/
WORKDIR /tmp/req_temp/
RUN pip3 install -r requirements.txt


WORKDIR /app
VOLUME /usr/share/c3nav
CMD ([ -d "/usr/share/c3nav/src/data" ] || \
        (mkdir /usr/share/c3nav/src/data \
         && python3 manage.py migrate \
         && python3 manage.py createsuperuser)) \
    && python3 manage.py migrate \
    && python3 manage.py runserver 0.0.0.0:8000
#USER root
#CMD mkdir /usr/share/c3nav/src/data && chmod 777 /usr/share/c3nav/src/data && bash