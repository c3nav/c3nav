# Using docker

For development purposes, we maintain a Dockerfile.

This is in heavy development currently and may be missing features. It does only support the django development server for now.

Data is persisted to the `data` directory in the repository root to facilitate the reproduction of bugs.

## Building images from Dockerfiles

Run the environment with

```
docker-compose up
```

If you’re starting c3nav for the first time, you need to initialize it and create a super user. Run:


```bash
docker-compose run c3nav python3 manage.py migrate
docker-compose run c3nav python3 manage.py compress
docker-compose run c3nav python3 manage.py compilemessages
docker-compose run c3nav python3 manage.py collectstatic --noinput
docker-compose run c3nav python3 manage.py createsuperuser
```
