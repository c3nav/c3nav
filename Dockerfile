FROM ubuntu:18.04
LABEL maintainer="morre+c3nav@mor.re"

WORKDIR /c3nav

# Install general dependencies
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y \
  git

# Install c3nav dependencies
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y \
  build-essential \
  gettext \
  python3-virtualenv \
  python3-pip \
  python3-dev \
  python3-tk \
  libmysqlclient-dev \
  librsvg2-bin

# Install c3nav
COPY src /c3nav

# Update and install our requirements
RUN pip3 install -U pip wheel setuptools
RUN pip3 install -r requirements.txt
RUN pip3 install -r requirements/redis.txt

# Set config file
RUN mkdir /etc/c3nav
COPY docker/c3nav.cfg /etc/c3nav

EXPOSE 8000
CMD ["/usr/bin/python3", "manage.py", "runserver", "0.0.0.0:8000"]
