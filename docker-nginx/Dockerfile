FROM nginx:stable

COPY pages /var/www/html/pages/
COPY templates/ /etc/nginx/templates/
COPY options-ssl-nginx.conf /etc/nginx/options-ssl-nginx.conf
COPY ssl-dhparams.pem /etc/nginx/ssl-dhparams.pem
