FROM debian:jessie

RUN apt-get update && apt-get install -y locales git build-essential \
    python3 python3-pip python3-dev \
    libpq-dev libmysqlclient-dev libmemcached-dev libgeos-dev gettext \
    librsvg2-bin --no-install-recommends

WORKDIR /

RUN dpkg-reconfigure locales \
 && locale-gen C.UTF-8 \
 && /usr/sbin/update-locale LANG=C.UTF-8 \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/* \
 && useradd -ms /bin/bash -d /c3nav -u 15371 c3navuser \
 && mkdir /etc/c3nav && mkdir /data && mkdir /data/map

ENV LC_ALL C.UTF-8

COPY src /c3nav/src
WORKDIR /c3nav/src

COPY deployment/docker/c3nav.bash /usr/local/bin/c3nav

RUN pip3 install -U pip wheel setuptools \
 && pip3 install -r requirements.txt -r requirements/mysql.txt -r requirements/postgres.txt \
	-r requirements/memcached.txt -r requirements/redis.txt gunicorn \
 && mkdir /static \
 && chown -R c3navuser:c3navuser /static /c3nav /data \
 && chmod +x /usr/local/bin/c3nav

USER c3navuser

EXPOSE 8000

ENTRYPOINT ["c3nav"]
CMD ["all"]
