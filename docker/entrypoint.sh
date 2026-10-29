#!/bin/sh
# Container start-up: wait for MySQL, apply pending migrations, then start the server.
# If MySQL is still starting, wait-db retries; if it never comes up the container
# exits with an error and Docker's restart policy tries again.
set -eu

python manage.py wait-db --timeout "${DB_WAIT_TIMEOUT:-120}"
python manage.py migrate
exec "$@"
