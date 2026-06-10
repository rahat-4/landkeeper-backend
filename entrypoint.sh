#!/bin/sh

echo "Waiting for PostgreSQL..."

while ! nc -z $POSTGRES_DOCKER_HOST $POSTGRES_PORT; do
  sleep 0.1
done

echo "PostgreSQL started"

echo "Running migrations..."
python manage.py migrate

echo "Starting server..."
exec "$@"
