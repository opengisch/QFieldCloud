FROM python:3.8.0-buster

# set work directory
WORKDIR /usr/src/app

# set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# install dependencies
RUN apt update \
    && apt install -y netcat-openbsd
RUN pip install --upgrade pip
COPY ./docker-app/requirements.txt /usr/src/app/requirements.txt
RUN pip install -r requirements.txt

# copy entrypoint.sh
COPY ./docker-app/entrypoint.sh /usr/src/app/entrypoint.sh

# copy project
COPY ./django-app /usr/src/app/

# run entrypoint.sh
ENTRYPOINT ["/usr/src/app/entrypoint.sh"]
