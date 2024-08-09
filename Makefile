SHELL:=bash
ENV_FILE:=.env.example

DJANGO_SUPERUSER_USERNAME="super_user"
DJANGO_SUPERUSER_EMAIL="qfield@cloud.gis"
DJANGO_SUPERUSER_PASSWORD="Ch@ngeM3Please;-)"

env:
	@echo "Configuring .env file from $(ENV_FILE)"
	@grep -v -e '^#' -e '^$$' $(ENV_FILE) > .env

build:
	@echo "Build images"
	docker compose build

run:
	@echo "Start QFieldCloud stack"
	docker compose up -d

#
# Run initial configuration
#
# See https://github.com/opengisch/qfieldcloud#launch-a-local-instance
# This is not really docker-friendly but django is to blame
#
init:
	@echo "Initialize QFieldCloud stack (run django migration && collect static files)"
	docker compose exec app python manage.py migrate
	docker compose exec app python manage.py collectstatic --noinput
	@echo "Waiting for 5s for workers to be up..."
	@sleep 5

status:
	@echo "Check QFieldCloud status"
	docker compose exec app python manage.py status

create-superuser:
	@echo "Create QFieldCloud super user"
	@export DJANGO_SUPERUSER_PASSWORD=$(DJANGO_SUPERUSER_PASSWORD)
	docker compose exec app python manage.py createsuperuser --noinput \
	--username $(DJANGO_SUPERUSER_USERNAME) --email $(DJANGO_SUPERUSER_EMAIL)

stop:
	@echo "Stop QFieldCloud stack"
	docker compose down
