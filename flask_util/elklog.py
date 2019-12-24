"""
# @Author  wk
# @Time 2019/10/11 11:13

"""
import socket
import re
import os
import time
import uuid
from datetime import datetime
import fcntl
import logging
from flask import request
from flask import g
import threading
from logging.handlers import TimedRotatingFileHandler


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


class ExecutedOutsideContext(Exception):
    """
    Exception to be raised if a fetcher was called outside its context
    """
    pass


class MultiContextRequestIdFetcher(object):
    """
    A callable that can fetch request id from different context as Flask, Celery etc.
    """

    def __init__(self):
        """
        Initialize
        """
        self.ctx_fetchers = []

    def __call__(self):

        for ctx_fetcher in self.ctx_fetchers:
            try:
                return ctx_fetcher()
            except ExecutedOutsideContext:
                continue
        return None

    def register_fetcher(self, ctx_fetcher):
        """
        Register another context-specialized fetcher
        :param Callable ctx_fetcher: A callable that will return the id or raise ExecutedOutsideContext if it was
         executed outside its context
        """
        if ctx_fetcher not in self.ctx_fetchers:
            self.ctx_fetchers.append(ctx_fetcher)


NO_REQUEST_ID = "none"


def dj_ctx_get_request_id():
    local = threading.local()
    req_id = getattr(local, 'request_id', NO_REQUEST_ID)
    return req_id


def flask_ctx_get_request_id():
    """
    Get request id from flask's G object
    :return: The id or None if not found.
    """
    from flask import _app_ctx_stack as stack  # We do not support < Flask 0.9

    if stack.top is None:
        raise ExecutedOutsideContext()

    g_object_attr = stack.top.app.config['LOG_REQUEST_ID_G_OBJECT_ATTRIBUTE']
    return g.get(g_object_attr, None)


current_request_id = MultiContextRequestIdFetcher()
current_request_id.register_fetcher(flask_ctx_get_request_id)


# DEFAULT_FORMAT = logging.Formatter("%(asctime)s - %(reqId)s - [%(levelname)s]  - %(filename)s - %(lineno)d - "
#                                    "[%(process)d:%(thread)d] - %(reqUri)s - [%(other)s]:  %(message)s")
DEFAULT_FORMAT = logging.Formatter("%(asctime)s - %(reqId)s - [%(levelname)s]  - %(filename)s - %(lineno)d - "
                                   "[%(process)d:%(thread)d] - %(message)s")


class RequestIDLogFilter(logging.Filter):
    """
    Log filter to inject the current request id of the request under `log_record.request_id`
    """

    def filter(self, log_record):
        log_record.reqId = current_request_id()
        return log_record


class HTTPInfo(object):
    def __init__(self, request_obj, resp_obj):
        super(HTTPInfo, self).__init__()
        self._request = request_obj
        self._response = resp_obj

    def get_req_uri(self):
        raise NotImplemented

    def get_http_method(self):
        raise NotImplemented

    @staticmethod
    def get_server_ip():
        return socket.gethostname()

    def get_client_ip(self):
        raise NotImplemented

    def get_sdk_version(self):
        raise NotImplemented

    @staticmethod
    def is_json_type(content_type):
        return content_type == 'application/json'

    def get_req_data(self):
        raise NotImplemented

    def get_agent_type(self):
        raise NotImplemented

    def get_status_code(self):
        return self._response.status_code

    def get_resp_size(self):
        return self._response.calculate_content_length()

    def get_resp_content_type(self):
        return self._response.content_type


class FlaskHttpInfo(HTTPInfo):

    def __init__(self, request_obj, resp_obj):
        super(FlaskHttpInfo, self).__init__(request_obj, resp_obj)

    def get_req_uri(self):
        return self._request.full_path

    def get_http_method(self):
        return self._request.method

    def get_client_ip(self):
        real_ip = self._request.headers.get('X-Real-Ip', request.remote_addr)
        return real_ip

    def get_sdk_version(self):
        return self._request.headers.get('SDKVersion')

    def get_req_data(self):
        if self.is_json_type(request.mimetype):
            data = self._request.data
        else:
            data = self._request.json
        return data

    def get_agent_type(self):
        """
        获取请求来源
        """
        browser = self._request.user_agent.browser
        platform = self._request.user_agent.platform
        uas = self._request.user_agent.string
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

    @staticmethod
    def get_client_version():
        return request.headers.get('SDKVersion')

    def get_userid(self):
        """
        获取账号ID
        :return:
        """
        userid = self._request.args.get('accountid') or self._request.args.get('account_id') or \
                 self._request.args.get('userid')
        return userid

    def get_login_token(self):
        """
        获取登录token
        :return:
        """
        token = self._request.headers.get('token') or self._request.args.get('sessionid')
        return token

    def get_info(self):
        data = dict()
        # data['request_start'] = datetime.utcnow()
        data['serverIp'] = self.get_server_ip()
        data['clientIp'] = self.get_client_ip()
        data['logSource'] = self.get_agent_type()
        data['reqMethod'] = self.get_http_method()
        data['reqData'] = self.get_req_data()
        data['reqUri'] = self.get_req_uri()
        data['device'] = self.get_agent_type()
        data['sdkVersion'] = self.get_sdk_version()
        data['userId'] = self.get_userid()
        data['token'] = self.get_login_token()
        data['respStat'] = self.get_status_code()
        data['respSizeB'] = self.get_resp_size()
        data['respContentType'] = self.get_resp_content_type()
        return data


class FlaskLogStash(object):
    def __init__(self, log_format=DEFAULT_FORMAT, level='DEBUG', app=None):
        self.log_format = log_format
        self.level = level
        self._logger = logging.getLogger('cc-logger')
        self._logger.setLevel(logging.DEBUG)
        self._logger.propagate = 0

        if app:
            self.app = app
            self.init_app(app)

    @property
    def last_req_id(self):
        try:
            return g.last_req_id
        except Exception:
            pass
        return getattr(self, '_last_req_id', None)

    @last_req_id.setter
    def last_req_id(self, value):
        """
        reqID
        :param value:
        :return:
        """
        self._last_req_id = value
        try:
            g.last_req_id = value
        except Exception:
            pass

    @property
    def last_request_start(self):
        """
        request开始的时间
        :return:
        """
        try:
            return g.last_request_start
        except Exception:
            pass
        return getattr(self, '_last_request_start', None)

    @last_request_start.setter
    def last_request_start(self, value):
        self._last_request_start = value
        try:
            g.last_request_start = value
        except Exception:
            pass

    @property
    def logger(self):
        return self._logger

    @logger.setter
    def logger(self, val):
        self._logger = val

    def init_app(self, app):
        log_path = app.config.get('LOGPATH', 'app.log')

        def __init_logger(logger, log_path, level, formatter):
            fh = MultiProcessTimedRotatingFileHandler(log_path, when='MIDNIGHT', interval=1)
            fh.setLevel(level)

            # 再创建一个handler，用于输出到控制台
            ch = logging.StreamHandler()
            ch.setLevel(level)
            # 定义handler的输出格式
            fh.setFormatter(formatter)
            ch.setFormatter(formatter)

            log_filter = RequestIDLogFilter()
            fh.addFilter(log_filter)
            ch.addFilter(log_filter)
            # 给logger添加handler
            logger.addHandler(fh)
            logger.addHandler(ch)
        __init_logger(self.logger, log_path, self.level, self.log_format)

        @app.before_request
        def before_request():
            self.last_req_id = str(uuid.uuid1().hex)
            self.last_request_start = datetime.utcnow()

        @app.after_request
        def after_request(response):
            if self.last_req_id:
                response.headers['X-req-ID'] = self.last_req_id
            http_info = FlaskHttpInfo(request, response).get_info()
            req_url = http_info.pop('reqUri', '')
            time_delta = datetime.utcnow() - self.last_request_start
            http_info['respTimeMs'] = int(time_delta.total_seconds()) * 1000 + int(time_delta.microseconds / 1000)
            log_http_str = "&".join("%s=%s" % (k, v) for k, v in http_info.items())
            extra_msg = "%s %s %s" % (req_url, log_http_str, 'Request')
            self.logger.debug(extra_msg)
            return response


