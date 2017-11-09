build:
	docker build -t haproxy/pyconfd . -t haproxy/pyconfd:latest

run:
	docker run \
	-e "APISERVERS=https://10.31.12.49:6443" \
	-e "SSL_CA_FILE=/etc/pyconfd/ca.pem" \
	-e "SSL_KEY_FILE=/etc/pyconfd/admin1-key.pem" \
	-e "SSL_CERT_FILE=/etc/pyconfd/admin1.pem" \
	-e "LOGLEVEL=debug" \
	-e "HAPROXY_RELOAD_CMD=/etc/init.d/haproxy reload" \
	-p 80:80 \
	-p 443:443 \
	-p 6379:6379 \
	haproxy/pyconfd

migrate:
	docker save haproxy/pyconfd:latest -o tmp_image.tar
	kpod -s overlay2 load < tmp_image.tar && rm -vf tmp_image.tar


daemon:
	docker run \
	-d \
	-e "APISERVERS=https://10.31.12.49:6443" \
	-e "SSL_CA_FILE=/etc/pyconfd/ca.pem" \
	-e "SSL_KEY_FILE=/etc/pyconfd/admin1-key.pem" \
	-e "SSL_CERT_FILE=/etc/pyconfd/admin1.pem" \
	-e "LOGLEVEL=debug" \
	-e "HAPROXY_RELOAD_CMD=/etc/init.d/haproxy reload" \
	-p 80:80 \
	-p 443:443 \
	-p 6379:6379 \
	h
