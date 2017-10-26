build:
	docker build -t haproxy/pyconfd .	

run:
	docker run \
	-e "APISERVERS=https://10.30.8.49:6443" \
	-e "SSL_CA_FILE=/etc/pyconfd/ca.pem" \
	-e "SSL_KEY_FILE=/etc/pyconfd/admin1-key.pem" \
	-e "SSL_CERT_FILE=/etc/pyconfd/admin1.pem" \
	-e "PYCONFD_DEBUG=debug" \
	-e "HAPROXY_RELOAD_CMD=/etc/init.d/haproxy  reload" \
	-p 80:80 \
	-p 443:443 \
	-p 6379:6379 \
	haproxy/pyconfd
