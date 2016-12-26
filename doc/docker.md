# Set up c3nav using docker

The easiest way to set up c3nav. Here's how to do it. This is just a simple temporary setup. There will be more information soon about setting up a production setup with docker.

## Get the docker container

aka. how to get the latest version.

### from Dockerhub

the images on dockerhub should are automatically built by the c3nav gitlab and should always be pretty much up to date

```
docker pull c3nav/c3nav
```

### from source

if you want to make _sure_ to get the newest version.

```
git clone https://github.com/c3nav/c3nav.git
cd c3nav
docker build -t c3nav .
cd ..
```

Keep in mind that you will have to replace `c3nav/c3nav` with `c3nav` in all `docker run` commands below.

## Create data and get maps

Create a data directory somewhere and clone the mappackages you want to use into it.

```
# example for the 33c3
mkdir -p 33c3-data/map/
cd 33c3-data/map/
git clone git@github.com:c3nav/c3nav-cch.git
git clone git@github.com:c3nav/c3nav-33c3.git
cd ../../
```

## load map data

This will read all the map data into a temporary SQLite database.

```
docker run --rm --name c3nav-33c3 -v `pwd`/33c3-data:/data c3nav/c3nav loadmap
```

## render map and build graph

This will take a while. You can skip this if you dont't want routing but just want to use the editor.

```
docker run --rm --name c3nav-33c3 -v `pwd`/33c3-data:/data c3nav/c3nav build
```

## add django configuration file
You need a configuration file in the docker container for django to run correctly.
Create the file `33c3-data/c3nav.cfg` with the following content

``` 
[c3nav]
public_packages=de.c3nav.cch,de.c3nav.33c3
[django]
hosts=*

``` 

## run c3nav

This will run a development server that you can reach at [localhost:8042/](http://localhost:8042/). The editor can be found at [localhost:8042/editor/](http://localhost:8042/editor/). **Never use this server for production purposes!**

```
docker run --rm --name c3nav-33c3 -p 8042:8000 -v `pwd`/33c3-data:/data -v `pwd`/33c3-data/c3nav.cfg:/etc/c3nav/c3nav.cfg  c3nav/c3nav runlocal
```

## after editing map data: save the map

After changing stuff with the editor, you may want to export the changes into the map package folders to submit a pull request. You can do so by running:

```
docker run --rm --name c3nav-33c3 -v `pwd`/33c3-data:/data c3nav/c3nav dumpmap
```
