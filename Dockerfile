FROM debian:stretch

MAINTAINER Volker Schwicking <github@blafoo.org>

ENV DEBIAN_FRONTEND noninteractive

RUN apt-get update && \
    apt-get install -y --no-install-recommends python3-requests haproxy python3-simplejson python3 python3-jinja2 && \
    touch /var/run/haproxy.pid && \
    chown haproxy:haproxy /var/run/haproxy.pid && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /etc/pyconfd

ADD ./src/etc/pyconfd/ /etc/pyconfd/
ADD ./src/etc/pyconfd/ca.pem /etc/pyconfd/ssl/ca.pem
ADD ./src/etc/pyconfd/admin1.pem /etc/pyconfd/admin1.pem
ADD ./src/etc/pyconfd/admin1-key.pem /etc/pyconfd/admin1-key.pem

ADD ./src/usr/local/bin/pyconfd.py /usr/local/bin/pyconfd
RUN chmod +x /usr/local/bin/pyconfd

EXPOSE 80 443 6379

CMD ["/usr/local/bin/pyconfd"]
