# Install c3nav manually

## Installation

This is just a simple temporary setup. There will be more information soon.

### Install dependencies

Install the needed dependencies.

#### Debian

```
apt-get install -y python3 python3-pip python3-venv python3-dev build-essential \
    libpq-dev libmysqlclient-dev libmemcached-dev libgeos-dev gettext librsvg2-bin
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

### Clone the map packages

For the 33c3, this would be c3nav-cch and c3nav-33c3:

```
cd data/maps/
git clone https://github.com/c3nav/c3nav-cch.git
git clone https://github.com/c3nav/c3nav-33c3.git
```

### Load the map packages

```
cd ../../
python3 manage.py loadmap
```

Confirm loading the map packages. You can always execute this command to update the map data in the database. This will also overwrite unexported mapdata in the database.

### Render the map and build the routing graph

Always do this after updating the mapdata. You can skip this step if you only want to use the Editor.

```
python3 manage.py rendermap
python3 manage.py buildgrap
```

FYI: You can find the renderings in the following folder: `data/render/`

### Run a development server

```
python3 manage.py runserver
```

You can now reach your c3nav instance at [http://localhost:8000/]. The editor can be found at [http://localhost:8000/editor/]. **Never use this server for production purposes!**

## Other things you can do now:

### Export map data

After changing stuff with the editor, you may want to export the changes into the map package folders to submit a pull request. You can do so by running.

```
python3 manage.py dumpmap
```

### Check map data

After manually editing map package files, you may want to check if the identation follows the style guide. Please to so if you manually edited files and want to submit a pull request.

```
python3 manage.py checkmap
```

### Draw the routing graph

Want to look at the routing graph? You can! Just run the following command, and graph renderings will appear in the render folder.

```
python3 manage.py drawgraph
```

## Production setup.

More information coming soon. If you already know Django, you will have no problems setting up for production yourself. Running c3nav any other way than with `runserver` (DEBUG=False) will automatically deactivate directly editing mapdata with the editor.
