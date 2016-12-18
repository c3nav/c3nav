# Install c3nav using docker

The easiest way to try out install c3nav. Here's how to do it. This is just a simple temporary setup. There will be more information soon about setting up a production setup with docker.

After installing docker, create a folder for all your c3nav stuff, clone the c3nav repository and build the docker image:

```
mkdir c3nav
cd c3nav
git clone git@github.com:c3nav/c3nav.git
cd c3nav
docker build -t c3nav .
```

Select the map packages you want to use. For the 33c3, this would be c3nav-cch and c3nav-33c3:

```
cd ..
mkdir maps
cd maps
git clone git@github.com:c3nav/c3nav-cch.git
git clone git@github.com:c3nav/c3nav-33c3.git
```

You can now start c3nav by starting the docker container. Don't forget to change the package paths (everything before the colon) according to your setup. You can change the name of the container to your liking.

```
docker run --rm --name c3nav-33c3 -p 8345:8000 \
    -v ~/c3nav/maps/c3nav-cch:/data/map/c3nav-cch \
    -v ~/c3nav/maps/c3nav-33c3:/data/map/c3nav-33c3 \
    c3nav all
```

This will read all the map data into a temporary SQLite database, render the map, build the graph and start a development server at http://localhost:8345/.

To add a custom file (to use a proper database, memcached, celery and so on, you can!) Create an empty folder with your c3nav.cfg file in it and it as an additional volume to your docker command. : `-v ~/c3nav/33c3-config:/etc/pretix`

Other options (instead of `all`) are:

- `editor`: just start a development server without rendering the map and building the graph first. this is sufficient to use the editor.
- `checkmap`: check if the package files are valid and formatted/indented currectly and optionally reindent them correctly (do this if you altered map package files manually).
- `build`: render the map and build the graph

Every command will read all map packages into the database and overwrite all changes. There is currently no way to export the changes made with the editor into the package folders (with docker) yet, but there will be soon. 
