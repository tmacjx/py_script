"""
操作类
    1.变更数据库
        python manage.py db init     初始化
        python manage.py db migrate  数据库更新
        python manage.py db upgrade  提交更新
    2.pep8检查
        python manage.py pep8
    3.单元测试
        python manage.py test
    4.覆盖率测试
        python manage.py coverage
"""

# todo 新增workflow commit之前执行脚本, 执行工作流以后，方可提供代码

import unittest
import coverage as cover

import pylint

from flask_migrate import Migrate, Manager, MigrateCommand

from live import create_app, db, config


app = create_app(config)


COV = cover.coverage(
    branch=True,
    include='live/*',
    omit=[
        'live/tests/*',
        'live/scripts/*',
        'live/config/*'
        'live/__init__.py'
    ]
)


COV.start()
manager = Manager(app)
migrate = Migrate(app, db)

manager.add_command('db', MigrateCommand)


@manager.command
def pep8():
    """Run the Pylint"""
    pass


@manager.command
def test():
    """Runs the unit tests without test coverage."""
    tests = unittest.TestLoader().discover('live/tests', pattern='test*.py')
    result = unittest.TextTestRunner(verbosity=2).run(tests)
    if result.wasSuccessful():
        return 0
    return 1


@manager.command
def coverage():
    """Runs the unit tests with coverage."""
    tests = unittest.TestLoader().discover('live/tests')
    result = unittest.TextTestRunner(verbosity=2).run(tests)
    if result.wasSuccessful():
        COV.stop()
        COV.save()
        print('Coverage Summary:')
        COV.report()
        COV.html_report()
        COV.erase()
        return 0
    return 1


@manager.command
def runserver():
    """Run the application with DEBUG"""
    # 127.0.0.1:5000
    app.run(debug=True)


if __name__ == '__main__':
    manager.run()
