# python-confd
A Python-Client that retrieves kubernetes endpoints from its API, generates a HAProxy configuration file and restarts/reloads HAProxy if any changes were found.

## Another one? Why not use confd?
Because kubernetes stores its data in etcd in protobuf format (since 1.3?, before that it was plain text) and confd does not (yet) support protobuf. Also confd queries etcd directly while pyconfd queries the kubernetes-api which i consider a cleaner way of communicating with kubernetes. 

Besides that, there is nothing wrong with confd, except that i dont know Go nor its text/template engine :-)

## What does it do exactly?
The script queries the Kubernetes-API-endpoint ```http(s):<apihost>:<port>/api/v1/endpoints``` and retrieves all endpoints configured in kubernetes (this, hopefully in your setup, requires some kind of authentication, but thats out of scope for this documentation). The configured endpoints are mapped into a simplified python dictionary which is then passed into the templates.

To have an endpoint present in the python-dict passed into the templates, it **_has_** to be annotated in kubernetes with the keywords **domain** and **proto**. If either is missing, the endpoint is ignored/skipped.

As an example we will make the kubernetes-dashboard available through our HAProxy.

The endpoint we want to make available:
```
$ kubectl get endpoints kubernetes-dashboard -n kube-system
NAME                   ENDPOINTS           AGE
kubernetes-dashboard   10.244.5.164:8443   13d
```

To have pyconfd use that endpoint we annotate it with **domain** and **proto**:
```
$ kubectl annotate endpoints kubernetes-dashboard domain=dashboard.k8s.cluster.com proto=https -n kube-system
endpoints "kubernetes-dashboard" annotated

$ kubectl describe endpoints kubernetes-dashboard -n kube-system
Name:        kubernetes-dashboard
Namespace:   kube-system
Labels:      k8s-app=kubernetes-dashboard
Annotations: domain=dashboard.k8s.cluser.com
             proto=https
Subsets:
  Addresses:        10.244.5.164
  NotReadyAddresses:    <none>
  Ports:
    Name    Port    Protocol
    ----    ----    --------
    <unset>    8443    TCP

Events:    <none>
```

**domain** is the url under which the service that endpoint (or rather the pods on the nodes) provides should be made available. Here i would like to have the dashboard available at ```https://dashboard.k8s.cluster.com``` This of course requires the fqdn to be mapped to the ip of our HAPRoxy-Server. If you dont have an fqdn to map, you can also put an ip-address here.

**proto** is set to **https**, because the dashboard is usually served with https configured. If your dashboard does not use SSL use **http** instead.

This two annotations for the dashboard translate into the following dict passed to the templates:

```python
{
    'dashboard.k8s.cluster.com': {
        'ips': [
            '10.244.5.164'
        ],
        'proto': 'https',
        'port': 8443
    }
}
```

If i were to add an http-service like grafana with annotations like **domain=grafana.k8s.cluster.com** and **proto=http**, it would look like this:

```python
{
    'dashboard.k8s.cluster.com': {
        'ips': [
            '10.244.5.164'
        ],
        'proto': 'https',
        'port': 8443
    },
    'grafana.k8s.cluster.com': {
        'ips': [
            '10.244.5.164'
        ],
        'proto': 'http',
        'port': 80
    }

}
```

What you do with that data in your templates is up to you. See below what the default templates do.

## The templates and configs
pyconfd supports two kinds of files in its template_dir. Templates named **\*.tmpl** and plain configs named **\*.conf**. If you require a certain order in which these files are processed, prefix them with digits like ```01-, 02-```, etc. Otherwise the order is whatever ```os.listdir()``` may return.

**\*.conf** files are added to the generated configuration file as is, use them for static values only.

The templates are in jinja. Each template receives the full dictionary described above. Its up to each template to extract just the data it needs. In the **02-http.tmpl** template all services that have **proto=http** are mapped into the same HAProxy-frontend while having seperate backends. The same is true for the https-template and **proto=https**. A rendered **02-http.tmpl** with the above dictionary
looks like this:

```
frontend http-in
    bind *:80
    mode http
    option httplog
    option httpclose
    option forwardfor
    reqadd X-Forwarded-Proto:\ http
    acl grafana_k8s_cluster_com hdr(host) -i grafana.k8s.cluster.com
    use_backend begrafana_k8s_cluster_com if grafana_k8s_cluster_com


# all http-backends
backend begrafana_k8s_cluster_com
    mode http
    balance roundrobin
    option forwardfor
    http-request set-header X-Forwarded-Port %[dst_port]
    http-request add-header X-Forwarded-Proto https if { ssl_fc }
    server 10_244_0_77 10.244.0.77:3000 check
```

As you can see, the **domain** field from the kubernetes annotation is converted into an variable and used to map frontend-http-requests to the corresponding http-backend. Any additional kubernetes-endpoint with **proto=http** would transfer into an additional ACL-Line and a standalone backend. The very same applies to **proto=https**, except that the ACL-line checks for the SNI-header instead of the HOST-header.
```
...
acl dashboard_k8s_cluster_com req.ssl_sni -i dashboard.k8s.cluster.com
use_backend bedashboard.k8s.cluster.com if dashboard_k8s_cluster_com

backend bedashboard.k8s.cluster.com
    mode tcp
    balance roundrobin
...
```

## Configuration
The script can be either configured with commandline parameters or environment variables, not
both at the same time. Supplying one parameter on the commandline disables environment awareness completely. I suggest using the parameters on the commandline for testing, once successful, transfer the configuration into your environment or ```docker -e``` parameters and run your container.

  --ssl-key [SSL_KEY_FILE]
                        The SSL-client-key-file to use (default: None)
  --ssl-cert [SSL_CERT_FILE]
                        The SSL-client-cert-file to use (default: None)
  --interval [REFRESH_INTERVAL]
                        The interval at which to check changes in the
                        endpoints (default: 30)
  --ssl-ca [SSL_CA_FILE]
                        The SSL-ca-file to check the api-servers certificate
                        (default: /etc/pyconfd/ca.pem)
  --template-dir [TEMPLATE_DIR]
                        Where to find the template files (default:
                        /etc/pyconfd)
  --haproxy-conf [HAPROXY_CONF]
                        The full path where to put the generated haproxy
                        config (default: /etc/haproxy/haproxy.cfg)
  --api-servers [APISERVERS]
                        List of api-server urls like https://<ip>:<port>, they
                        are tried in order (default: [])
  --haproxy-chk-cmd [HAPROXY_CHECK_CMD]
                        The command to check the syntax of a haproxy config
                        (default: /usr/sbin/haproxy -c -q -f)
  --haproxy-reload-cmd [HAPROXY_RELOAD_CMD]
                        The command to reload/restart haproxy (default:
                        /etc/init.d/haproxy reload )

The same variables are supported when set in the environment.

| **Variablename**  | **default value** |
|-------------------|-------------------|
| APISERVERS        | ''                |
| LOGLEVEL          | INFO              |
| SSL_KEY_FILE      | ''                |
| SSL_CERT_FILE     | ''                |
| SSL_CA_FILE       | ''                |
| REFRESH_INTERVAL  | 30                |
| TEMPLATE_DIR      | /etc/pyconfd      |
| HAPROXY_CONF      | /etc/haproxy/haproxy.cfg |
| HAPROXY_CHECK_CMD | /usr/sbin/haproxy -c -q -f |
| HAPROXY_RELOAD_CMD| /bin/systemctl reload-or-restart haproxy |


## Testing pyconfd with your kubernetes-api
All examples assume a debian-stretch-default HAPRoxy installation and systemd. Adjust
**--haproxy-\*** parameters accordingly if your setup differs.

In a non SSL-setup setup,  without any authentication (seriously?), not containerized, the
only required parameter is '--api-servers':
```
./pyconfd.py --api-servers https://10.31.12.49:6443
```

With SSL-client-certificates, self-signed CA, not containerized and debugging enabled:
```
./pyconfd.py \
   --ssl-key /etc/pyconfd/admin-key.pem \
   --ssl-cert /etc/pyconfd/admin.pem \
   --ssl-ca /etc/pyconfd/ca.pem \
   --api-servers https://10.31.12.49:6443 \
   --log-level debug \
```

Same as above, but try multiple API-servers in order or appearance
```
./pyconfd.py \
   --ssl-key /etc/pyconfd/admin-key.pem \
   --ssl-cert /etc/pyconfd/admin.pem \
   --ssl-ca /etc/pyconfd/ca.pem \
   --api-servers https://10.31.12.49:6443,https://10.31.12.51:6443,https://10.31.13.49:6443 \
   --log-level debug
```
Once the tests are finished, update the Makefile to suite your needs.

## Building and starting the container
Depending on your kubernetes-setup, update the SSL-files in ./src/etc/pyconfd/*.pem with proper
SSL-key, SSL-cert and CA information. This repo only contains empty dummy files to successfully build the container image. If you dont set ```SSL_KEY_FILE``` or ```SSL_CERT_FILE``` the dummy files will be ignored anyway.

Build the image
```
make build
```
Run the image in the foreground
```
make run
```

Once the image is built and the Makefile updated (beware of spaces instead of the required TABs), run the container
``` 
make daemon
```

