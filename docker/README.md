# Docker Containers for c3nav


## Requirements for building

You need docker buildx and qemu-user-static and a buildkit builder that is using the docker-container or kubernetes
driver if you want to build multi-arch images.

This are the necessary steps to get it working on arch linux

```bash
pacman -Sy docker-buildx qemu-user-static
docker buildx create --driver=docker-container --bootstrap --use
```

Additonally you need to be signed in into the github container registry. A guid for how to do this can be found 
[here](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry#authenticating-with-a-personal-access-token-classic).


## Building

You can run the `build.sh` script in two modes. If you run it without any arguments it uses your local git tree
including any uncommitted changes to build the docker containers.

If you run `./build.sh git` it will do a fresh git checkout of the same commit as you currently on for building.
