FROM python:3.7-buster

# Environment variable
ENV PYTHONUNBUFFERED 1

# change work directory
RUN mkdir -p /app
WORKDIR /app

ADD requirements.txt /app/
RUN pip3 install -r requirements.txt

EXPOSE $PORT

CMD ["manage.py runserver 0.0.0.0:$PORT"]
