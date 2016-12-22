FROM python:alpine

RUN echo "@testing http://dl-4.alpinelinux.org/alpine/edge/testing" >> /etc/apk/repositories \
 && echo "@community http://dl-4.alpinelinux.org/alpine/edge/community" >> /etc/apk/repositories \
 && apk update \
 && apk add --update git g++ libc-dev tcl tk libpq libjpeg-turbo-dev lapack@community openblas@community postgresql-dev libmemcached geos@testing gettext librsvg-dev \
 && mkdir /etc/c3nav \
 && mkdir /data \
 && mkdir /data/map \
 && ln -s /usr/include/locale.h /usr/include/xlocale.h

ENV LC_ALL C.UTF-8

COPY src /c3nav/src
WORKDIR /c3nav/src

COPY deployment/docker/c3nav.bash /usr/local/bin/c3nav

RUN pip install -r requirements.txt -r requirements/production-extra.txt -r requirements/postgres.txt \
                -r requirements/memcached.txt -r requirements/redis.txt gunicorn \
 && chmod +x /usr/local/bin/c3nav

RUN python manage.py collectstatic
 &&	python manage.py compress
 &&	python manage.py compilemessages

EXPOSE 8000

ENTRYPOINT ["c3nav"]
CMD ["all"]
