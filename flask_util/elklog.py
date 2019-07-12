import os
import re
import json
import uuid
import time
import logging
import fcntl
import socket
import traceback
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime


JSON_SERIALIZER = json.dumps
REQ_ID_GENERATOR = uuid.uuid1
_request_util = None
# 1 API相关
PLATFORM_CODE = 'ccapi'


def iso_time_format(datetime_):
    return '%04d-%02d-%02dT%02d:%02d:%02d.%03dZ' % (
        datetime_.year, datetime_.month, datetime_.day, datetime_.hour, datetime_.minute, datetime_.second,
        int(datetime_.microsecond / 1000))


def is_flask_present():
    # noinspection PyPep8,PyBroadException
    try:
        import flask
        return True
    except:
        return False


if is_flask_present():
    from flask import request as request_obj
    import flask as flask

    _current_request = request_obj
    _flask = flask


class MultiProcessTimedRotatingFileHandler(TimedRotatingFileHandler):
    _stream_lock = None

    def doRollover(self):
        """
        do a rollover; in this case, a date/time stamp is appended to the filename
        when the rollover happens.  However, you want the file to be named for the
        start of the interval, not the current time.  If there is a backup count,
        then we have to get a list of matching filenames, sort them and remove
        the one with the oldest suffix.
        """
        if self.stream:
            self.stream.close()
            self.stream = None
        # get the time that this sequence started at and make it a TimeTuple
        currentTime = int(time.time())
        dstNow = time.localtime(currentTime)[-1]
        t = self.rolloverAt - self.interval
        if self.utc:
            timeTuple = time.gmtime(t)
        else:
            timeTuple = time.localtime(t)
            dstThen = timeTuple[-1]
            if dstNow != dstThen:
                if dstNow:
                    addend = 3600
                else:
                    addend = -3600
                timeTuple = time.localtime(t + addend)
        # dfn = self.baseFilename + '.' + time.strftime(self.suffix, timeTuple)
        dfn = self.rotation_filename(self.baseFilename + "." +
                                     time.strftime(self.suffix, timeTuple))
        # 加锁保证rename的进程安全
        if not os.path.exists(dfn) and os.path.exists(self.baseFilename):
            fcntl.lockf(self.stream_lock, fcntl.LOCK_EX)
            try:
                if not os.path.exists(dfn) and os.path.exists(self.baseFilename):
                    os.rename(self.baseFilename, dfn)
            finally:
                fcntl.lockf(self.stream_lock, fcntl.LOCK_UN)
        # 加锁保证删除文件的进程安全
        if self.backupCount > 0:
            if self.getFilesToDelete():
                fcntl.lockf(self.stream_lock, fcntl.LOCK_EX)
                try:
                    files_to_delete = self.getFilesToDelete()
                    if files_to_delete:
                        for s in files_to_delete:
                            os.remove(s)
                finally:
                    fcntl.lockf(self.stream_lock, fcntl.LOCK_UN)
        if not self.delay:
            # _open默认是以‘a'的方式打开，是进程安全的
            self.stream = self._open()
        newRolloverAt = self.computeRollover(currentTime)
        while newRolloverAt <= currentTime:
            newRolloverAt = newRolloverAt + self.interval
        # If DST changes and midnight or weekly rollover, adjust for this.
        if (self.when == 'MIDNIGHT' or self.when.startswith('W')) and not self.utc:
            dstAtRollover = time.localtime(newRolloverAt)[-1]
            if dstNow != dstAtRollover:
                if not dstNow:  # DST kicks in before next rollover, so we need to deduct an hour
                    addend = -3600
                else:           # DST bows out before next rollover, so we need to add an hour
                    addend = 3600
                newRolloverAt += addend
        self.rolloverAt = newRolloverAt

    @property
    def stream_lock(self):
        if not self._stream_lock:
            self._stream_lock = self._openLockFile()
        return self._stream_lock

    def _getLockFile(self):
        # Use 'file.lock' and not 'file.log.lock' (Only handles the normal "*.log" case.)
        if self.baseFilename.endswith('.log'):
            lock_file = self.baseFilename[:-4]
        else:
            lock_file = self.baseFilename
        lock_file += '.lock'
        return lock_file

    def _openLockFile(self):
        lock_file = self._getLockFile()
        return open(lock_file, 'w')


class FlaskRequestAdapter(object):
    def get_url(self):
        return _current_request.url

    def get_path(self):
        return _current_request.full_path

    def get_content_length(self):
        return _current_request.content_length

    def get_method(self):
        return _current_request.method

    def get_server_ip(self):
        return socket.gethostname()

    def get_client_ip(self):
        real_ip = _current_request.headers.get('X-Real-Ip', _current_request.remote_addr)
        return real_ip

    def get_http_header(self):
        return _current_request.headers

    def get_user_agent(self):
        return _current_request.headers.get('user_agent')

    def get_agent_type(self):
        """
        获取请求来源
        """
        browser = _current_request.user_agent.browser
        platform = _current_request.user_agent.platform
        uas = _current_request.user_agent.string
        client = 'web'
        browser_tuples = ('safari', 'chrome')
        if platform == 'iphone':
            if browser not in browser_tuples:
                client = 'iphone'
        elif platform == 'android':
            if browser not in browser_tuples:
                client = 'AN'
        elif re.search('iPad', uas):
            if browser not in browser_tuples:
                client = 'iPad'
        elif re.search('Windows Phone OS', uas):
            client = 'WinPhone'
        elif re.search('BlackBerry', uas):
            client = 'BlackBerry'
        return client

    def get_userid(self):
        """
        获取账号ID
        :return:
        """
        userid = _current_request.args.get('accountid') or _current_request.args.get('account_id') \
                 or _current_request.args.get('userid')
        return userid

    def get_login_token(self):
        """
        获取登录token
        :return:
        """
        token = _current_request.headers.get('token') or _current_request.args.get('sessionid')
        return token

    def get_req_data(self):
        req_data = _current_request.data
        # 如果不为空，则转json
        if bytes.decode(req_data):
            data = _current_request.json or _current_request.form
            return data
        else:
            return None

    def set_req_id(self, value):
        _flask.g.request_id = value

    def get_req_id_in_request_context(self):
        return _flask.g.get('request_id', None)


class FlaskResponseAdapter(object):
    def get_status_code(self, response):
        return response.status_code

    def get_response_size(self, response):
        return response.calculate_content_length()

    def get_content_type(self, response):
        return response.content_type


class RequestUtil(object):
    def __init__(self, request_adapter_class=FlaskRequestAdapter, response_adapter_class=FlaskResponseAdapter):
        self.request_adapter = request_adapter_class()
        self.response_adapter = response_adapter_class()

    def get_reqId(self):
        reqId = self.request_adapter.get_req_id_in_request_context()
        return reqId


class RequestInfo(dict):
    """
        class that keep HTTP request information for request instrumentation logging
    """

    def __init__(self, request, **kwargs):
        super(self.__class__, self).__init__(**kwargs)
        self.request_start = datetime.utcnow()
        req_adapter = _request_util.request_adapter
        self.serverIp = socket.gethostname()
        self.clientIp = req_adapter.get_client_ip()
        self.logSource = req_adapter.get_agent_type()
        self.userId = req_adapter.get_userid()
        self.token = req_adapter.get_login_token()
        self.reqMethod = req_adapter.get_method()
        self.reqUrl = req_adapter.get_url()
        # print(self.reqUrl)
        self.reqUri = req_adapter.get_path()
        self.reqData = req_adapter.get_req_data()
        self.device = req_adapter.get_user_agent()
        # 生成唯一的reqID, 用于track request的周期
        req_id = str(REQ_ID_GENERATOR().hex)
        req_adapter.set_req_id(req_id)

    # noinspection PyAttributeOutsideInit
    def update_response_status(self, response):
        """
        update response information into this object, must be called before invoke request logging statement
        :param response:
        """
        response_adapter = _request_util.response_adapter
        time_delta = datetime.utcnow() - self.request_start
        self.respTimeMs = int(time_delta.total_seconds()) * 1000 + int(time_delta.microseconds / 1000)
        self.respStat = response_adapter.get_status_code(response)
        self.respSizeB = response_adapter.get_response_size(response)
        self.respContentType = response_adapter.get_content_type(response)

    def pack_data(self):
        res = {}
        for key in self.__dict__:
            res[key] = self.__dict__.get(key)
        return res


class ReqLogFormat(logging.Formatter):
    """
    req/resp相关日志
    """
    def format(self, record):
        request_adapter = _request_util.request_adapter
        json_log_object = {"type": "request",
                           "ascTime": iso_time_format(datetime.utcnow()),
                           "service": PLATFORM_CODE,
                           "reqId": _request_util.get_reqId(),
                           "reqUri": request_adapter.get_path(),
                           "serverIp": request_adapter.get_server_ip(),
                           "clientIp": request_adapter.get_client_ip(),
                           "logSource": request_adapter.get_agent_type(),
                           "userId": request_adapter.get_userid(),
                           "token": request_adapter.get_login_token(),
                           "reqMethod": request_adapter.get_method(),
                           "reqData": request_adapter.get_req_data(),
                           "device": request_adapter.get_user_agent(),
                           "respStat": record.request_info.respStat,
                           "respTimeMs": record.request_info.respTimeMs,
                           "respSizeB": record.request_info.respSizeB,
                           "respContentType": record.request_info.respContentType,
                           "msg": record.getMessage()
                           }

        return JSON_SERIALIZER(json_log_object)


# after request记录
class WebLogFormat(logging.Formatter):
    """
    web log
    """
    def get_exc_fields(self, record):
        if record.exc_info:
            exc_info = self.format_exception(record.exc_info)
        else:
            exc_info = record.exc_text
        return {
            'exc_info': exc_info,
            'filename': record.filename,
        }

    @classmethod
    def format_exception(cls, exc_info):

        return ''.join(traceback.format_exception(*exc_info)) if exc_info else ''

    def format(self, record):
        request_adapter = _request_util.request_adapter
        json_log_object = {"type": "log",
                           "ascTime": iso_time_format(datetime.utcnow()),
                           "service": PLATFORM_CODE,
                           "reqId": _request_util.get_reqId(),
                           "logger": record.name,
                           "thread": record.threadName,
                           "level": record.levelname,
                           "module": record.module,
                           "line_no": record.lineno,
                           "serverIp": request_adapter.get_server_ip(),
                           "clientIp": request_adapter.get_client_ip(),
                           "logSource": request_adapter.get_agent_type(),
                           "msg": record.getMessage()
                           }

        if hasattr(record, 'props'):
            json_log_object.update(record.props)

        if record.exc_info or record.exc_text:
            json_log_object.update(self.get_exc_fields(record))

        return JSON_SERIALIZER(json_log_object)


class FlaskLogStash(object):
    def __init__(self, app=None, req_format=ReqLogFormat, web_format=WebLogFormat):
        self._web_format = web_format()
        self._req_format = req_format()
        self._request_logger = logging.getLogger('flask-request-logger')
        self._request_logger.setLevel(logging.DEBUG)
        self._web_logger = logging.getLogger('flask-web-logger')
        self._web_logger.setLevel(logging.DEBUG)
        if app:
            self.app = app
            self.init_app(app)

    @property
    def request_logger(self):
        return self._request_logger

    @property
    def web_logger(self):
        return self._web_logger

    def init_app(self, app):
        if not is_flask_present():
            raise RuntimeError("flask is not available in system runtime")
        from flask.app import Flask
        if not isinstance(app, Flask):
            raise RuntimeError("app is not a valid flask.app.Flask app instance")

        global _request_util
        _request_util = RequestUtil(request_adapter_class=FlaskRequestAdapter,
                                    response_adapter_class=FlaskResponseAdapter)

        log_path = app.config.get('LOGPATH', 'app.log')

        def __init_logger(logger, log_path, formatter):
            fh = MultiProcessTimedRotatingFileHandler(log_path, when='MIDNIGHT', interval=1)
            fh.setLevel(logging.DEBUG)

            # 再创建一个handler，用于输出到控制台
            ch = logging.StreamHandler()
            ch.setLevel(logging.DEBUG)
            # 定义handler的输出格式
            fh.setFormatter(formatter)
            ch.setFormatter(formatter)

            # 给logger添加handler
            logger.addHandler(fh)
            logger.addHandler(ch)

        # todo 两个logger共用一个文件
        __init_logger(self.request_logger, log_path, self._req_format)
        __init_logger(self.web_logger, log_path, self._web_format)

        # from flask import current_app
        # current_app.
        from flask import g

        @app.before_request
        def before_request():
            # todo req记录
            g.request_info = RequestInfo(_current_request)

        @app.after_request
        def after_request(response):
            # print(app.before_request_funcs)
            request_info = g.request_info
            response.headers.add('requestID', g.request_id)
            request_info.update_response_status(response)
            self.request_logger.debug("Request", extra={'request_info': request_info})
            return response












