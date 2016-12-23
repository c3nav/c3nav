FROM python:slim

RUN apt-get update && apt-get install -y git build-essential \
    libpq-dev libmysqlclient-dev libmemcached-dev libgeos-dev gettext \
    librsvg2-bin --no-install-recommends \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/* \
 && mkdir /etc/c3nav && mkdir /data && mkdir /data/map

COPY src /c3nav/src
WORKDIR /c3nav/src

COPY deployment/docker/c3nav.bash /usr/local/bin/c3nav

RUN pip install -r requirements.txt -r requirements/mysql.txt -r requirements/postgres.txt \
	-r requirements/memcached.txt -r requirements/redis.txt gunicorn \
 && mkdir /static \
 && chmod +x /usr/local/bin/c3nav \
 && python manage.py collectstatic --no-input \
 &&	python manage.py compress \
 &&	python manage.py compilemessages

ENTRYPOINT ["c3nav"]
CMD ["all"]
