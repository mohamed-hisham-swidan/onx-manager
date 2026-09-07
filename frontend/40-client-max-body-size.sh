#!/bin/sh
set -e

# Support admin-configured client_max_body_size via environment variable
SIZE="${CLIENT_MAX_BODY_SIZE:-1024m}"
if [ -f /etc/nginx/conf.d/default.conf ]; then
    sed -i "s/client_max_body_size [^;]*;/client_max_body_size ${SIZE};/" /etc/nginx/conf.d/default.conf
fi
