# coding: utf-8
import os
import traceback
import subprocess
from threading import Timer
import logging
import uuid
import json
import time

STATUS_NOT_FOUND = '404 Not Found'


class HttpError(Exception):
    def __init__(self, status, message=''):
        self.status = status
        self.message = message


log = None


def get_logger(filename, level):
    log = logging.getLogger(__name__)
    log.setLevel(getattr(logging, level))
    if not filename:
        log_handler = logging.StreamHandler()
    else:
        log_handler = logging.FileHandler(filename)
    log_handler.setLevel(level)
    log_formatter = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    log_handler.setFormatter(log_formatter)
    log.addHandler(log_handler)
    return log


class Application(object):
    def __init__(self, environ, start_response):
        self.environ = environ
        self._start_response = start_response
        request_id = environ.get('REQUEST_ID')
        if not request_id:
            request_id = uuid.uuid4().get_hex()
        self.request_id = request_id
        self.scripts_dir = environ['MONITORING_SCRIPTS_DIR']

    def log(self, level, message='', **extra):
        extra = dict(extra, request_id=self.request_id)
        message += ' ' + json.dumps(extra)
        if level == 'EXCEPTION':
            log.exception(message)
        else:
            log.log(getattr(logging, level), message)

    def get_scripts_list(self):
        return os.listdir(self.scripts_dir)

    @staticmethod
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

    def execute_script_or_dir(self, name):
        start = time.time()
        path = os.path.join(self.scripts_dir, name)
        if os.path.isdir(path):
            success = True
            message = []
            scripts = os.listdir(path)
            if not scripts:
                raise Exception('No scripts in directory %s' % path)
            for script in scripts:
                res = self.execute_script(os.path.join(path, script))
                success = success and res['success']
                message.append('%s: %s' % (script, res['message']))
            result = {'success': success, 'message': '\n'.join(message)}
        else:
            result = self.execute_script(path)
        result['time'] = time.time() - start
        return result

    def route(self):
        try:
            method = self.environ['REQUEST_METHOD']
            uri = self.environ['PATH_INFO']
            self.log('DEBUG', 'Accepted request', method=method, uri=uri)
            if method != 'GET':
                self.log('INFO', 'Unsupported method', method=method)
                raise HttpError(STATUS_NOT_FOUND)
            script_name = uri.strip('/')
            if script_name not in self.get_scripts_list():
                self.log('INFO', 'Unknown script', script_name=script_name)
                raise HttpError(STATUS_NOT_FOUND)
            result = self.execute_script_or_dir(script_name)
            self.log('INFO', 'Script executed', result=result, script_name=script_name)
            message = result['message']
            if message:
                message = '\n' + message
            message = ('CHECK PASSED' if result['success'] else 'CHECK FAILED') + message + '\n'
            if result['success']:
                self._start_response('200 OK', [])
            else:
                self._start_response('500 Internal Server Error', [])
            return [message]
        except HttpError as e:
            self.log('DEBUG', 'Returning http error', status=e.status)
            self._start_response(e.status, [])
            return [e.message]
        except:
            log.exception('Unhandled exception')
            self._start_response('500 Internal server error', [])
            return [traceback.format_exc()]


def application(environ, start_response):
    global log
    if log is None:
        log = get_logger(environ.get('MONITORING_LOG_FILE'), 'DEBUG')
    try:
        result = Application(environ, start_response).route()
    except:
        log.exception('Unhandled exception 2')
        raise
    return result


if __name__ == '__main__':
    os.environ['MONITORING_SCRIPTS_DIR'] = '/home/w/projects/monitoring/scripts'

    from wsgiref.simple_server import make_server

    httpd = make_server('localhost', 8080, application)
    httpd.serve_forever()
