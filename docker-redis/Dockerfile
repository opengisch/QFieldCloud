FROM redis:6.0.8

ADD ./redis.conf /redis.conf

# Add the user to redis conf
ARG REDIS_PASSWORD
RUN echo "\n\nuser default +@all ~* on >$REDIS_PASSWORD" >> /redis.conf
CMD [ "redis-server", "/redis.conf" ]