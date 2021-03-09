# following command starts up local containers and then starts sass processer which compiles scss files to css.
docker-compose up -d && sass --watch docker-app/qfieldcloud/core/web/staticfiles/scss/qfieldcloud.scss docker-app/qfieldcloud/core/web/staticfiles/css/qfieldcloud.css
