# Install c3nav manually

## Installation

This is just a simple temporary setup. There will be more information soon.

### Install dependencies

Install the needed dependencies.

#### Debian

```
apt-get install -y build-essential gettext gfortran libfreetype6-dev libgeos-dev \
    libjpeg-dev libmemcached-dev liblapack-dev libmysqlclient-dev libopenblas-dev \
    libpq-dev librsvg2-bin pkg-config python3 python3-dev python3-pip python3-venv
```

Feel free to add guides for other operating systems.

### Clone the repository

Create a folder for all your c3nav stuff and clone the c3nav repository.

```
mkdir c3nav
cd c3nav
git clone https://github.com/c3nav/c3nav.git
cd c3nav
```

### Create a virtual environment

This will create a virtual environment so the installed python packages are not installed globally on your system.

```
virtualenv -p python3 env
source env/bin/activate
```

Always run the latter command before executing anything from c3nav.


### Install python dependencies

```
cd src/
pip3 install -U pip wheel setuptools
pip3 install -r requirements.txt
```

*Skip to the next step if you just want a development setup or use the editor.*

Wanna use redis, mysql, postgres, memcached or deploy c3nav in a public place?

pip3 install -r requirements/mysql.txt -r requirements/postgres.txt \
             -r requirements/memcached.txt -r requirements/redis.txt gunicorn

### Add Configuration

You need this to configure your own database, memcached, and the message queue. You can skip this step for now for a development setup – everything will work out of the box.

### Migrate the database

This will create the needed database tables (and a temporary database, if you did not configure a different one) or update the database layout if needed. You should always execute this command after pulling from upstream.

```
python3 manage.py migrate
```

### Build the translations

You can skip this step if English is enough for you.

```
python3 manage.py compilemessages
```

### Build the map

**No documentation is available for this. We're working on it. Please stop mistaking documentation from years ago for something that is still up to date.**

### Run a development server

```
python3 manage.py runserver
```

You can now reach your c3nav instance at [localhost:8000/](http://localhost:8000/). The editor can be found at [localhost:8000/editor/](http://localhost:8000/editor/). **Never use this server for production purposes!**

