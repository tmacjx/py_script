"""
# @Author  wk
# @Time 2020/4/3 14:55

"""
import time
import grequests
import logging
import requests
import json
from requests.exceptions import RequestException
from urllib.error import URLError, HTTPError
import xmltodict


logger = logging.getLogger("test")


def xml_to_dict(xml_str):
    data_dict = xmltodict.parse(xml_str)
    return data_dict


def api_retry(retry_num=3, exception=Exception, raise_except=True):
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
            if isinstance(exception, (RequestException, URLError, HTTPError)):
                pass
                # 发送报警
                # send_alarm(message=str(exception.args))
            if not success:
                if raise_except:
                    raise exception
                else:
                    return {'result': "FAIL"}
        return wrapper
    return decorator


@api_retry(raise_except=False)
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

    before_time = int(time.time() * 1000)
    response = requests.request(http_method, url, params=query_params,
                                headers=headers, data=data,
                                files=files, timeout=timeout)
    consume_time = int(time.time() * 1000) - before_time
    logger.info('请求API {url} {params} {data} 耗时{consume_time} '.format(
        url=url, params=query_params, data=post_args, consume_time=consume_time))

    content_type = response.headers.get('content-type', 'application/json')
    if "application/json" in content_type:
        resp_data = response.json()
    elif 'xml' in content_type:
        resp_data = xml_to_dict(response.content)
    else:
        resp_data = response.text
    http_status = response.status_code
    if http_status not in [200, 201]:
        logger.error('请求API失败 {url} {data} {status} '
                     '{resp_data}'.format(url=url, data=data, status=http_status, resp_data=resp_data))
        return
    if resp_data.get('result') in {'OK', 'ok', 1} or bool(resp_data.get('success')) is True \
            or data.get('isValid') in {'True', 'true', True}:
        resp_data['result'] = 'OK'
    else:
        resp_data['result'] = 'FAIL'
    return resp_data


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
