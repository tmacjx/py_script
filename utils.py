"""
# @Author  wk
# @Time 2019/12/24 11:43

"""
import json
import datetime
from datetime import datetime


# json.dumps(data, cls=JsonExtendEncoder)
class JsonExtendEncoder(json.JSONEncoder):
    """
        This class provide an extension to json serialization for datetime/date.
    """
    def default(self, o):
        """
            provide a interface for datetime/date
        """
        if isinstance(o, datetime.datetime):
            return o.strftime('%Y-%m-%d %H:%M:%S')
        elif isinstance(o, datetime.date):
            return o.strftime('%Y-%m-%d')
        else:
            return json.JSONEncoder.default(self, o)