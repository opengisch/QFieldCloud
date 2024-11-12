FROM nginx:stable

COPY pages /var/www/html/pages/
COPY templates/ /etc/nginx/templates/
COPY options-ssl-nginx.conf /etc/nginx/options-ssl-nginx.conf
COPY 99-autoreload.sh /docker-entrypoint.d/99-autoreload.sh

RUN chmod 755 /docker-entrypoint.d/99-autoreload.sh
