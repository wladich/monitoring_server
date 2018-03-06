# coding: utf-8
import os
import traceback
import subprocess
from threading import Timer

STATUS_NOT_FOUND = '404 Not Found'


class HttpError(Exception):
    def __init__(self, status, message=''):
        self.status = status
        self.message = message


def get_scripts_list(path):
    return os.listdir(path)

def execute_script(path):
    p = subprocess.Popen(path, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    timeout = {'value': False}

    def on_timeout():
        p.kill()
        timeout['value'] = True

    timer = Timer(10, on_timeout, [])
    try:
        timer.start()
        stdout, stderr = p.communicate()
    finally:
        timer.cancel()
    if timeout['value']:
        return {'success': False, 'message': 'Timeout'}
    message = '\n'.join(filter(None, [stdout.strip(), stderr.strip()]))
    return {'success': p.returncode == 0, 'message': repr(message) if message else ''}


def execute_script_or_dir(path, name):
    path = os.path.join(path, name)
    if os.path.isdir(path):
        success = True
        message = []
        scripts = os.listdir(path)
        if not scripts:
            raise Exception('No scripts in directory %s' % path)
        for script in scripts:
            res = execute_script(os.path.join(path, script))
            success = success and res['success']
            message.append('%s: %s' % (script, res['message']))
        return {'success': success, 'message': '\n'.join(message)}
    else:
        return execute_script(path)


def application(environ, start_response):
    try:
        method = environ['REQUEST_METHOD']
        uri = environ['PATH_INFO']
        scripts_dir = environ['MONITORING_SCRIPTS_DIR']
        if method != 'GET':
            raise HttpError(STATUS_NOT_FOUND)
        script_name = uri.strip('/')
        if script_name not in get_scripts_list(scripts_dir):
            raise HttpError(STATUS_NOT_FOUND)
        result = execute_script_or_dir(scripts_dir, script_name)
        start_response('200 OK', [])
        message = result['message']
        if message:
            message = '\n' + message
        message = ('CHECK PASSED' if result['success'] else 'CHECK FAILED') + message + '\n'
        return [message]
    except HttpError as e:
        start_response(e.status, [])
        return [e.message]
    except:
        start_response('500 Internal server error', [])
        return [traceback.format_exc()]


if __name__ == '__main__':
    os.environ['MONITORING_SCRIPTS_DIR'] = '/home/w/projects/monitoring/scripts'

    from wsgiref.simple_server import make_server

    httpd = make_server('localhost', 8080, application)
    httpd.serve_forever()
