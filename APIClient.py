"""
# @Author  wk
# @Time 2020/4/3 14:55

"""
import time
import grequests
import logging
import requests
import json


logger = logging.getLogger("test")


def request_api(
        url,
        http_method='GET',
        headers=None,
        query_params=None,
        post_args=None,
        files=None,
        timeout=5):

    if query_params is None:
        query_params = {}
    if post_args is None:
        post_args = {}
    if headers is None:
        headers = {}

    data = None
    if files is None:
        data = json.dumps(post_args)

    if http_method in ("POST", "PUT", "DELETE") and not files:
        headers['Content-Type'] = 'application/json; charset=utf-8'

    headers['Accept'] = 'application/json'

    response = requests.request(http_method, url, params=query_params,
                                headers=headers, data=data,
                                files=files, timeout=timeout)
    content_type = response.headers.get('content-type', 'application/json')
    if "application/json" in content_type:
        resp_data = response.json()
    else:
        resp_data = response.text
    http_status = response.status_code
    if http_status not in [200, 201]:
        logger.error('请求API失败 {url} {data} {status} '
                     '{resp_data}'.format(url=url, data=data, status=http_status, resp_data=resp_data))
        return
    logger.info('请求API成功 {url} {data} {status} {resp_data}'.format(
        url=url, data=data, status=http_status, resp_data=resp_data))
    return resp_data


def api_retry(retry_num=3, exception=Exception):
    def decorator(func):
        def wrapper(*args, **kwargs):
            nonlocal exception
            success = False
            for i in range(0, retry_num):
                logger.debug('request count %s %s %s' % (i, args, kwargs))
                try:
                    response = func(*args, **kwargs)
                except Exception as e:
                    logger.error('业务相关error %s' % e, exc_info=True)
                    exception = e
                    continue
                else:
                    return response
            # 如果重试三次失败, 则raise
            if not success:
                raise exception
        return wrapper
    return decorator


class APIClient(object):
    exception = Exception

    def __init__(self, base_url, headers=None, http_service=requests):
        if headers is None:
            headers = {}
        self.base_url = base_url
        self.headers = headers
        self.http_service = http_service

    @api_retry()
    def fetch_json(
            self,
            uri_path,
            http_method='GET',
            headers=None,
            query_params=None,
            post_args=None,
            files=None,
            timeout=5):
        """ Fetch some JSON from Intel Atlas """

        # explicit values here to avoid mutable default values
        if headers is None:
            headers = self.headers
        if query_params is None:
            query_params = {}
        if post_args is None:
            post_args = {}

        # if files specified, we don't want any data
        data = None
        if files is None:
            data = json.dumps(post_args)

        # set content type and accept headers to handle JSON
        if http_method in ("POST", "PUT", "DELETE") and not files:
            headers['Content-Type'] = 'application/json; charset=utf-8'

        headers['Accept'] = 'application/json'

        # construct the full URL without query parameters
        if uri_path[0] == '/':
            uri_path = uri_path[1:]
        url = '%s/%s' % (self.base_url, uri_path)

        before_time = int(time.time() * 1000)
        if self.http_service == grequests:
            req = [self.http_service.request(http_method, url, params=query_params,
                                             headers=headers, data=data,
                                             files=files, timeout=timeout)]
            response = grequests.map(req)[0]
        else:
            response = self.http_service.request(http_method, url, params=query_params,
                                                 headers=headers, data=data,
                                                 files=files, timeout=timeout)
        consume_time = int(time.time() * 1000) - before_time

        try:
            resp_data = response.json()
        except Exception as e:
            logger.debug('解析json error %s' % e)
            resp_data = response.text

        http_status = response.status_code
        if http_status not in [200, 201]:
            raise self.exception('请求API失败 {url} {data} {status} '
                                 '{resp_data}'.format(url=url, data=data, status=http_status, resp_data=resp_data))
        else:
            logger.info('请求API成功 {url} {data} {status} {resp_data} 耗时{consume_time} '.format(
                url=url, data=data, status=http_status, resp_data=resp_data, consume_time=consume_time))

        return resp_data
