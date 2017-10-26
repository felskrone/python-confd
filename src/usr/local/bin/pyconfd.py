#!/usr/bin/python3
'''
Gathers endpoints for services from kubernetes-api and generates a haproxy.cfg from it.
Since not all endpoints should always be exposed, the endpoints have to be annotated to
be considered for haproxy-config generation. The required keywords are
domain - The domain-name under which the service is made avaliable. Can be any string you desire.
proto - The protocol to expose the service with. All endpoints with proto=http go in the same
        haproxy-frontend which forwards requests by HTTP-HOST-Header information to the correspoding
        haproxy-http-backend.
        The same applies to proto=https, except that requests are forwarded by SSL-SNI-Header
        to the respective https-haproxy-backend.

If proto is set to anything else, for example 'redis', the/a template needs to extract that
endpoints info manually. See Readme.md for a more detailed explanation.
'''

# We are fine with lower case constants
# pylint: disable=invalid-name
# pylint: disable=missing-docstring

import os
import sys
import logging
import datetime
import argparse
import random
import string
import subprocess
import shutil
import time
from hashlib import md5 as hashmd5
from jinja2 import Environment
from jinja2 import FileSystemLoader
import simplejson
import requests

log = None

class ParseCAAction(argparse.Action):
    '''
    Helper class to support ssl-ca=<string> and --ssl-ca=False
    simultaniously.
    '''
    def __call__(self, parser, namespace, values, option_string=None):
        if values == 'False':
            setattr(namespace, self.dest, False)
        else:
            setattr(namespace, self.dest, values)


class ArgParser(object):
    '''
    Parse commandline arguments.
    '''
    def __init__(self):
        self.main_parser = argparse.ArgumentParser()
        self.add_args()

    def add_args(self):
        '''
        Add options to argparse instance
        '''
        self.main_parser.add_argument(
            '--log-level',
            type=str,
            default='INFO',
            dest='loglevel',
            nargs='?',
            required=False,
            help='The loglevel of the logger'
        )

        self.main_parser.add_argument(
            '--ignore-proxy-env',
            type=bool,
            default=True,
            const=True,
            dest='ignore_proxy_env',
            nargs='?',
            required=False,
            help=(
                'Whether to ignore http_proxy / https_proxy settings '
                'from environemnt (default: True)'
            )
        )


        self.main_parser.add_argument(
            '--ssl-key',
            type=str,
            default=None,
            dest='ssl_key_file',
            nargs='?',
            required=False,
            help='The SSL-client-key-file to use (default: None)'
        )

        self.main_parser.add_argument(
            '--ssl-cert',
            type=str,
            default=None,
            dest='ssl_cert_file',
            nargs='?',
            required=False,
            help='The SSL-client-cert-file to use (default: None)'
        )

        self.main_parser.add_argument(
            '--interval',
            type=int,
            default=30,
            dest='refresh_interval',
            nargs='?',
            required=False,
            help=(
                'The interval at which to check changes in '
                'the endpoints (default: 30)'
            )
        )

        self.main_parser.add_argument(
            '--ssl-ca',
            type=str,
            default='/etc/pyconfd/ca.pem',
            dest='ssl_ca_file',
            nargs='?',
            required=False,
            action=ParseCAAction,
            help=(
                'The SSL-ca-file to check the api-servers '
                'certificate (default: /etc/pyconfd/ca.pem)'
            )
        )

        self.main_parser.add_argument(
            '--template-dir',
            type=str,
            default='/etc/pyconfd/',
            dest='template_dir',
            nargs='?',
            required=False,
            help='Where to find the template files (default: /etc/pyconfd)'
        )

        self.main_parser.add_argument(
            '--haproxy-conf',
            type=str,
            default='/etc/haproxy/haproxy.cfg',
            dest='haproxy_conf',
            nargs='?',
            required=False,
            help=(
                'The full path where to put the generated haproxy '
                'config (default: /etc/haproxy/haproxy.cfg)'
            )
        )

        self.main_parser.add_argument(
            '--api-servers',
            type=str,
            default='',
            dest='apiservers',
            nargs='?',
            required=True,
            help=(
                'List of  api-server urls like https://<ip>:<port>, '
                'they are tried in order (default: [])'
            )
        )

        self.main_parser.add_argument(
            '--haproxy-chk-cmd',
            type=str,
            default='/usr/sbin/haproxy -c -q -f',
            dest='haproxy_check_cmd',
            nargs='?',
            required=False,
            help=(
                'The command to check the syntax of a haproxy '
                'config (default: /usr/sbin/haproxy -c -q -f)'
            )
        )

        self.main_parser.add_argument(
            '--haproxy-reload-cmd',
            type=str,
            default='/etc/init.d/haproxy reload',
            dest='haproxy_reload_cmd',
            nargs='?',
            required=False,
            help=(
                'The command to reload/restart haproxy '
                '(default: /bin/systemctl reload-or-restart haproxy)'
            )
        )

    def parse_args(self):
        return self.main_parser.parse_args()


class MyLogger(object):
    '''
    Basic logging class for easy logging to the console
    '''
    def __init__(self, level=logging.INFO):
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.getLevelName(level.upper()))
        ch_format = logging.Formatter('%(levelname)s - %(message)s')
        conh = logging.StreamHandler()
        conh.setFormatter(ch_format)
        conh.setLevel(logging.getLevelName(level.upper()))
        self.logger.addHandler(conh)

    def info(self, msg):
        self.logger.info(msg)

    def error(self, msg):
        self.logger.error(msg)

    def debug(self, msg):
        self.logger.debug(msg)


def load_tmpls(conf):
    '''
    Load all templates (files named *.tmpl) from configured
    template dir and return jinja-environment
    '''
    log.info('Loading templates *.tmpl from {0}'.format(conf['template_dir']))
    j2tmpls = Environment(
        loader=FileSystemLoader(conf['template_dir']),
        trim_blocks=True)
    return j2tmpls


def md5(fname):
    hash_md5 = hashmd5()
    with open(fname, "rb") as md5f:
        for chunk in iter(lambda: md5f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def writeconf(conf, data):
    '''
    Write the generated data to a temporary file and run syntax checks
    on it. If successful, the temporary file is moved to its destination
    and the haproxy service is reloaded via systemctl
    '''
    # Generate a random string for temporary config
    tmp_name = '/tmp/haproxy.cfg.' + ''.join(
        random.choice(string.ascii_uppercase) for _ in range(5))

    try:
        with open(tmp_name, 'w') as tmp_f:
            tmp_f.write(''.join(data))
        log.debug('Wrote temporary config to {0}'.format(tmp_name))
    except (IOError, OSError) as w_err:
        log.error('Failed to write generated config: {0}'.format(str(w_err)))

    cmd = conf['haproxy_check_cmd'] + ' ' + tmp_name
    log.debug('Executing syntax check: {0}'.format(cmd))
    if subprocess.call(cmd.split()) == 0:
        log.info('Syntax-check of temporary config at {0} successful'.format(tmp_name))

        md5_inst_conf = md5(conf['haproxy_conf'])
        md5_tmp_name = md5(tmp_name)

        log.debug(
            'md5sums {0}: {1}, {2}: {3}'.format(
                conf['haproxy_conf'],
                md5_inst_conf,
                tmp_name,
                md5_tmp_name
            )
        )

        if md5_inst_conf == md5_tmp_name:
            log.info('No changes in endpoints found, skipping installation of {0}'.format(tmp_name))
            os.remove(tmp_name)
        else:
            log.info('Installing {0} config to {1}'.format(tmp_name, conf['haproxy_conf']))
            shutil.move(tmp_name, conf['haproxy_conf'])

            log.debug('Executing haproxy reload: {0}'.format(conf['haproxy_reload_cmd']))
            if subprocess.call(conf['haproxy_reload_cmd'].split()) == 0:
                log.info('Successfully reloaded haproxy!')
            else:
                log.error('Failed to reload haproxy via systemctl!')
    else:
        msg = 'Syntax-check of temporary config at {0} failed, aborting...'
        raise SyntaxError(msg.format(tmp_name))


def gen(svc_map=None, conf=None, extra=None, j2_map=None):
    '''
    Run through all files in template_dir and either add their contents (*.conf-files)
    or generate them as templates (*.tmpl-files) before adding the result. Its good
    practice to prefix the file with digits like 00, 01, 02, etc. to get ordered results.
    '''

    conf_files = sorted(os.listdir(conf['template_dir']))
    gen_data = []
    extra = {
        'curdate': str(datetime.datetime.now())
    }

    # Run through all the configs and templates and either add
    # them to the config to generate (*.conf files) or render
    # them (*.tmpl files).
    for hafile in conf_files:

        if hafile.endswith('.conf'):
            log.debug('Adding plain config {0}'.format(hafile))
            with open(os.path.join(conf['template_dir'], hafile), 'r') as cfile:
                gen_data += cfile.readlines()
                gen_data += '\n'

        # if we got a template, pass the data to it and render
        elif hafile.endswith('.tmpl'):
            log.debug('Adding/Generating template {0}'.format(hafile))
            tmpl = j2_map.get_template(hafile)
            gen_data += tmpl.render(domains=svc_map, extra=extra)

    writeconf(conf, gen_data)

def parse_endpoints(data):
    '''
    Parse the endpoints and look for services annotated
    with our keywords domain and proto. Ignore the others.
    '''

    svc_retr = {}

    log.info('Checking annotations of retrieved endpoints...')

    for endp in data['items']:
        try:
            domain = endp['metadata']['annotations']['domain']
            proto = endp['metadata']['annotations']['proto']
            ports = endp['subsets'][0]['ports'][0]['port']

            svc_retr[domain] = {}
            svc_retr[domain]['proto'] = proto
            svc_retr[domain]['port'] = ports

            for ips in endp['subsets'][0]['addresses']:
                if 'ips' in svc_retr[domain]:
                    svc_retr[domain]['ips'].append(ips['ip'])
                else:
                    svc_retr[domain]['ips'] = []
                    svc_retr[domain]['ips'].append(ips['ip'])
            log.info('Found service {0}'.format(domain))
            log.info(
                'Endpoints: {0}'.format(
                    [''.join([x, ':', str(ports)]) for x in svc_retr[domain]['ips']]
                )
            )

        except KeyError:
            log.debug(
                'Skipping endpoint {0}, no/not matching annotations'.format(
                    endp['metadata']['name']
                )
            )
        except Exception as perr:
            raise SyntaxError('Failed tp parse annotations: {0}'.format(perr))

    return svc_retr


def get_endpoints(conf):
    '''
    Gather endpoints from kubernetes api. If more than one api-server is supplied,
    they are tried in order of appearance on the commandline.
    '''
    if conf['ignore_proxy_env']:
        for k in list(os.environ.keys()):
           if k.lower().endswith('_proxy'): 
                del os.environ[k]

    for apisrv in conf['apiservers'].split(','):

        try:
            # switch definition of verify depending on passed
            # or missing client certs and verify parameters
            if isinstance(conf['ssl_ca_file'], str):
                if os.path.isfile(conf['ssl_ca_file']):
                    verify = conf['ssl_ca_file']
                else:
                    msg = 'Specified ca file {0} does not exist'
                    raise IOError(msg.format(conf['ssl_ca_file']))

            elif isinstance(conf['ssl_ca_file'], bool):
                verify = conf['ssl_ca_file']
            else:
                verify = True

            # make the request either with client certs or without
            # and server-cert verification or insecure ssl
            if conf['ssl_cert_file'] and conf['ssl_key_file']:
                if not os.path.isfile(conf['ssl_cert_file']): 
                    msg = 'Specified cert file {0} does not exist'
                    raise IOError(msg.format(conf['ssl_cert_file']))

                if not os.path.isfile(conf['ssl_key_file']): 
                    msg = 'Specified key file {0} does not exist'
                    raise IOError(msg.format(conf['ssl_key_file']))

                msg = 'Getting endpoints from API {0} with SSL-client-certs'
                log.info(msg.format(apisrv))
                data = requests.get(
                    apisrv + '/api/v1/endpoints',
                    cert=(conf['ssl_cert_file'], conf['ssl_key_file']),
                    verify=verify
                )
            else:
                msg = 'Getting endpoints from API {0} with SSL-verification disabled!'
                log.info(msg.format(apisrv))
                data = requests.get(
                    apisrv + '/api/v1/endpoints',
                    verify=verify
                )

            if data.status_code != 200:
                msg = 'Failed to load endpoints API returned code: {0}:{1}!'
                raise ValueError(
                    msg.format(
                        data.status_code,
                        data.text
                    )
                )
            else:
                msg = 'Successfully received endpoints from api: {0}'
                log.info(msg.format(data.status_code))

        except Exception as apierr:
            msg = 'Failed to load endpoints from API: {0}!'
            raise SyntaxError(msg.format(apierr))

        try:
            k8seps = simplejson.loads(data.text)
            return parse_endpoints(k8seps)
        except simplejson.scanner.JSONDecodeError as json_err:
            msg = 'Failed to parse JSON-response from API: {0}'
            raise simplejson.scanner.JSONDecodeError(
                msg.format(json_err)
            )

def conf_from_env():
    env_vars = {
        'APISERVERS': '',
        'LOGLEVEL': 'INFO',
        'SSL_KEY_FILE': '',
        'SSL_CERT_FILE': '',
        'SSL_CA_FILE': '',
        'REFRESH_INTERVAL': 30,
        'TEMPLATE_DIR': '/etc/pyconfd',
        'HAPROXY_CONF': '/etc/haproxy/haproxy.cfg',
        'HAPROXY_CHECK_CMD': '/usr/sbin/haproxy -c -q -f',
        'HAPROXY_RELOAD_CMD': '/etc/init.d/haproxy reload',
        'IGNORE_PROXY_ENV': True
    }
    found_vars = {}

    for envvar, default in env_vars.items():
        found_vars[envvar.lower()] = os.getenv(envvar, default)

    return found_vars


if __name__ == '__main__':
    if len(sys.argv) <= 1:
        args = conf_from_env()
    else:
        args = vars(ArgParser().parse_args())

    log = MyLogger(level=args['loglevel'])

    while True:
        try:
            log.info('#########################################')
            log.info('Run started at {0}'.format(str(datetime.datetime.now())))
            log.info('#########################################')
            j2_env = load_tmpls(args)
            svcs = get_endpoints(args)
            gen(svc_map=svcs, conf=args, j2_map=j2_env)
            log.info('#########################################')
            log.info('Run finished at {0}'.format(str(datetime.datetime.now())))
            log.info('#########################################')
            time.sleep(args['refresh_interval'])
        except Exception as run_exc:
            log.error('Execution failed: {0}'.format(run_exc))
            time.sleep(args['refresh_interval'])
