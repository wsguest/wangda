# -*- coding:utf-8 -*-

import logging.handlers
import os
from random import randint
import sys
import threading
from base64 import encodebytes
from datetime import (timedelta, date, datetime)
from enum import IntEnum
from time import time, sleep

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

# log settings
log_level = logging.DEBUG
logger = logging.getLogger()
logger.setLevel(log_level)
formatter = logging.Formatter('%(message)s')
ch = logging.StreamHandler()
ch.setFormatter(formatter)
ch.setLevel(logging.INFO)
logger.addHandler(ch)

fh = logging.handlers.RotatingFileHandler(filename='wangda.log', maxBytes=10 * 1024 * 1024)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', '%Y-%m-%d %H:%M:%S')
fh.setFormatter(formatter)
fh.setLevel(logging.DEBUG)
logger.addHandler(fh)


# Status Code enum
class StatusCode(IntEnum):
    Starting = 0
    Learning = 1
    Finished = 2
    Timeout = 4


# main class
class wangda(object):
    BASE_URL = 'https://wangda.chinamobile.com/'
    SYS_URL = BASE_URL + 'api/v1/system/'
    COS_URL = BASE_URL + 'api/v1/course-study/'
    AUTH_URL = BASE_URL + 'oauth/api/v1/'
    AES_KEY = 'd8cg8gVakEq9Agup'

    def __init__(self, username, password=None):
        self.req = requests.Session()
        self.username = username
        self.password = password
        self.token = None
        self.token_time = datetime.now()
        self.token_expires = 3600  # seconds
        self.task_list = []
        self.PROC_EVENT = threading.Event()
        self.PROC_THREAD = None

    def authorized(func):
        def check_login(self, *args, **kwargs):
            if self.token and datetime.now() <= self.token_time + timedelta(seconds=self.token_expires):
                return func(self, *args, **kwargs)

            success = self.login(self.username, self.password)
            if success:
                return func(self, *args, **kwargs)
            else:
                return None

        return check_login

    def login(self, username=None, password=None):
        if not username:
            username = self.username
        if not password and self.password:
            password = self.password
        if not username or not password:
            return False
        key = ''.join([f'{randint(0, 255):02x}' for _ in range(0, 16)])
        r1 = self.req.post(wangda.AUTH_URL + 'members',
                           data={'key': key,
                                 'passwordType': 'static',
                                 'username': username,
                                 'password': password}).json()

        logger.debug(f'login1: {r1}')
        if 'pass' not in r1:
            return False

        r2 = self.req.post(wangda.AUTH_URL + 'auth',
                           data={'key': key,
                                 'userid': r1['members'][0]['id'],
                                 'check_token': r1['check_token']}).json()

        logger.debug(f'login2: {r2}')
        if 'access_token' not in r2:
            return False

        self.token = f'{r2["token_type"]}__{r2["access_token"]}'
        self.token_time = datetime.now()
        self.token_expires = r2['expires_in']
        self.req.headers.update({'Authorization': self.token})

        return True

    @authorized
    def _get_new_courses(self):
        url = wangda.SYS_URL + f'home-module?homeConfigId=001&clientType=1&_={time()}'
        r = self.req.get(url).json()
        items = []
        for conf in r:
            if conf['homeModuleId']:
                continue
            conf_id = conf['id']
            url1 = wangda.SYS_URL + f'home-content?moduleHomeConfigId={conf_id}&size=4&clientType=1&_={time()}'
            r1 = self.req.get(url1).json()
            items.append(r1)

        return map(lambda item: {'id': item['id'], 'finishStatus': 0}, items)

    @authorized
    def _get_home_courses(self):
        url = wangda.COS_URL + f'course-front/front?type=0&publishClient=1&companyType=0' \
                               f'&orderBy=0&order=2&page=1&pageSize=20&_={time()}'
        r = self.req.get(url).json()
        return map(lambda item: {'id': item['id'], 'finishStatus': item['finishStatus']}, r['items'])

    @authorized
    def _search_courses(self, search_key='', status=StatusCode.Starting):
        url = wangda.COS_URL + f'course-front/full-search?type={status}&publishClient=1' \
                               f'&searchContent={search_key}&page=1&pageSize=30&_={time()}'
        r = self.req.get(url).json()

        return map(lambda item: {'id': item['id'], 'finishStatus': item['finishStatus']}, r['items'])

    @authorized
    def _get_my_courses(self, status=StatusCode.Learning):
        url = wangda.COS_URL + f'course-study-progress/personCourse-list?businessType=0&findStudy=0' \
                               f'&finishStatus={status}&studyTimeOrder=desc&page=1&pageSize=100&_={time()}'
        r = self.req.get(url).json()
        return map(lambda item: {'id': item['courseId'], 'finishStatus': item['finishStatus']}, r['items'])

    @authorized
    def _purchase_course(self, course_id):
        # url = wangda.SYS_URL + 'collect?businessId=%s' % course_id
        # rsb = self.req.get(url)
        url = wangda.COS_URL + f'course-front/course-purchase?id={course_id}'
        r1 = self.req.get(url).json()
        logger.debug(f'purchase_course:{r1}')

        if 'code' in r1 and r1['code'] == '200':
            return True
        return False

    @authorized
    def _register_study(self, course_id):
        url = wangda.COS_URL + 'course-front/registerStudy'
        data = {'type': 1, 'courseId': course_id}
        r1 = self.req.post(url, data=data).json()
        logger.debug(f'registerStudy:{r1}')

        if 'finishStatus' in r1 and r1['finishStatus'] != '2':
            return True
        return False

    @authorized
    def _get_course_info(self, course_id):
        url = wangda.COS_URL + f'course-front/info/{course_id}'
        r = self.req.get(url).json()
        logger.debug(f'getCourseInfo:{r}')
        return r

    @authorized
    def _get_course_progress(self, sec_id):
        r = self.req.post(wangda.COS_URL + 'course-front/course-progress', data={'ids': [sec_id]}).json()
        logger.debug(f'_get_course_progress:{r}')
        return r

    @authorized
    def get_study_seconds(self, start_date=None, end_date=None):
        if not end_date:
            end_date = date.today()  # + timedelta(days=1)

        if not start_date:
            start_date = end_date - timedelta(days=1)

        url = wangda.COS_URL + f'course-study-progress/statistics?startTime={start_date.strftime("%Y-%m-%d")}' \
                               f'&endTime={end_date.strftime("%Y-%m-%d")}&_={time()}'
        r = self.req.get(url).json()
        logger.debug(f'get_study_seconds:{r}')

        if 'studyTime' in r:
            return r['studyTime']['0']
        else:
            return -1

    @authorized
    def _start_progress(self, section_id):
        # return logid
        url = wangda.COS_URL + f'course-front/start-progress/{section_id}?clientType=0&_={time()}'
        r = self.req.get(url).json()
        logger.debug(f'_start_progress:{r}')
        if 'id' in r:
            return r['id']
        else:
            return None

    @staticmethod
    def aes_encrypt(text):
        key = wangda.AES_KEY
        while len(key) % 16 != 0:
            key += '\0'
        aes = AES.new(key.encode('utf-8'), AES.MODE_ECB)
        pad_pkcs7 = pad(text.encode('utf-8'), AES.block_size, style='pkcs7')
        encrypt_aes = aes.encrypt(pad_pkcs7)
        encrypted_text = str(encodebytes(encrypt_aes), encoding='utf-8').rstrip('\n')
        return encrypted_text

    @authorized
    def get_courses(self, search_key=None, count=5):
        if search_key:
            courses = list(self._search_courses(search_key, status=StatusCode.Starting))
            if len(courses) < count:
                courses += list(self._search_courses(search_key, status=StatusCode.Learning))
            if len(courses) < count:
                courses += list(self._search_courses(search_key, status=StatusCode.Finished))
            if len(courses) < count:
                logger.debug(f'not found courses: {search_key}')
                return None
        else:
            # starting
            courses = list(self._get_my_courses(status=StatusCode.Starting))
            if len(courses) < 5:
                logger.debug('no starting courses')
                # unfinished
                courses += list(self._get_my_courses(status=StatusCode.Learning))
            if len(courses) < count:
                logger.debug('no unfinished courses')
                courses += list(self._get_home_courses())
            if len(courses) < count:
                logger.debug('no home courses found')
                courses += list(self._get_new_courses())

        if not courses or len(courses) < 1:
            return None
        else:
            return courses

    @authorized
    def add_task(self, seconds=7200, courses=None):
        try:
            if seconds < 0:
                logger.debug('invalid parameters. seconds < 0 ')
                return 0
            if not courses:
                logger.debug('find more courses to learn. ')
                courses = self.get_courses()

            if not courses:
                logger.debug('no courses found')
                return 0

            task_count = 0
            for course in courses:
                if seconds <= 0:
                    break

                cid = course['id']
                logger.debug(f'courseId: {cid}')
                if self._purchase_course(cid) and self._register_study(cid):
                    course_info = self._get_course_info(cid)
                    # logger.debug('courseInfo2: %s' % (course_info))
                    if len(course_info['courseChapters']) < 1:
                        continue

                    for chap in course_info['courseChapters']:
                        if seconds <= 0:
                            break
                        logger.debug(f'chapInfo:{chap["name"]}')

                        for sec in chap['courseChapterSections']:
                            logger.debug(f'secInfo: {sec}')

                            sec_id = sec['id']
                            if 'referenceId' in sec and sec['referenceId']:
                                sec_id = sec['referenceId']

                            in_list = False
                            for task in self.task_list:
                                if task['sec_id'] == sec_id:
                                    in_list = True
                                    break
                            if in_list:
                                continue

                            sec_seconds = sec['timeSecond']
                            if sec_seconds < 10:
                                continue

                            progress = self._get_course_progress(sec_id)
                            location = 0
                            logger.debug(f'course progress: {progress}')
                            if progress and len(progress) > 0:
                                percent = progress[0]['completedRate']
                                if not percent:
                                    percent = 0
                                location = progress[0]['lessonLocation']
                                if not location:
                                    location = 0
                                # print(percent)
                                if percent >= 100 or progress[0]['finishStatus'] == '2':
                                    continue

                            study_loc = int(location)
                            log_id = self._start_progress(sec_id)

                            self.task_list.append({'log_id': log_id,
                                                   'sec_id': sec_id,
                                                   'sec_title': sec['name'],
                                                   'sec_time': sec_seconds,
                                                   'start_loc': study_loc,
                                                   'start_time': time(),
                                                   'finished': 0})
                            seconds -= (sec_seconds - study_loc)
                            task_count += 1
                            if seconds <= 0:
                                break
        except Exception as ex:
            logger.error(ex)
            task_count = -1
        finally:
            pass

        return task_count

    @authorized
    def _update_progress(self, task):
        url = wangda.COS_URL + 'course-front/video-progress'
        # try to hack time, not work
        # study_time = total_time
        log_id = task['log_id']
        total_time = task['sec_time']
        study_time = int(time() - task['start_time'])
        loc = task['start_loc'] + study_time
        if loc > total_time:
            loc = total_time
        data = {'logId': log_id,
                'resourceTotalTime': total_time,
                'studyTime': study_time,
                'lessonLocation': loc,
                'organizationId': 1}
        for k in data.keys():
            data[k] = wangda.aes_encrypt(str(data[k]))
        r = self.req.post(url, data=data).json()

        return r

    @authorized
    def clear_task(self):
        self.task_list.clear()

    @classmethod
    def send_dynamic_password(cls, username):
        req = requests.session()
        url = cls.AUTH_URL + 'dynamic-password'
        key = ''.join([f'{randint(0, 255):02x}' for _ in range(0, 16)])
        r = req.post(url, data={'key': key, 'username': username}).json()

        if 'errorCode' in r:
            return False
        else:
            return True

    @authorized
    def start_process_task(self, interval=300):
        if self.PROC_THREAD:
            if self.PROC_THREAD.is_alive():
                logger.debug('process thread is already running.')
                return

        stop = self.PROC_EVENT
        stop.clear()

        def process():
            while not stop.is_set():
                terminated = stop.wait(interval)
                if terminated:
                    break
                task_count = 0
                for task in self.task_list:
                    if task['finished'] == StatusCode.Finished:
                        continue
                    task_count += 1
                    rp = self._update_progress(task)
                    logger.debug(f'process task: {task["sec_title"]}: {rp}')
                    if rp:
                        if 'errorCode' in rp:
                            pass
                        elif 'completedRate' in rp and rp['completedRate'] >= 100:
                            task['finished'] = StatusCode.Finished
                    self.token_time = datetime.now()
                if task_count < 1:
                    logger.debug('all tasks are finished.')
                    self.stop_process_task()
            logger.debug('stop processing tasks')

        self.PROC_THREAD = threading.Thread(target=process)
        self.PROC_THREAD.setDaemon(True)
        self.PROC_THREAD.start()
        logger.debug(f'start to process tasks, check interval:{interval}')

    @authorized
    def stop_process_task(self):
        stop = self.PROC_EVENT
        stop.set()


if __name__ == '__main__':

    user_name = ''
    password = ''
    go_minutes = 120
    file = 'wangda.dat'
    if os.path.isfile(file):
        with open(file, 'r') as f:
            lines = f.read().splitlines()
            if len(lines) > 2:
                user_name = lines[0]
                password = lines[1]
                if lines[2].isdigit():
                    go_minutes = int(lines[2])

    if not user_name:
        user_name = input('请输入手机号：')
        password = input('请输入密码：')
        if not user_name or not password:
            logger.error('用户密码不能为空。')
            sys.exit(1)
        go_minutes = int(input('请输入挂机分钟数（默认120分钟）：') or '120')

    print('如需帮助联系微信:wsguest')
    logger.info(f'{user_name} 正在登录...请稍候')
    w = wangda(user_name, password)
    login = w.login()
    if not login:
        logger.error('登录失败，用户或密码错误，请重新输入或删除历史记录文件。')
        sys.exit(1)
    else:
        with open(file, 'w') as f:
            f.write(user_name + '\n')
            f.write(password + '\n')
            f.write(str(go_minutes) + '\n')

    today = date.today()
    first_month_day = today - timedelta(days=today.day - 1)
    seconds = w.get_study_seconds(start_date=first_month_day)
    logger.info(f'用户:{user_name}\t本月时长:{seconds // 3600}小时{(seconds // 60) % 60}分')

    cnt = w.add_task(go_minutes * 60)
    if cnt > 0:
        logger.info('列表:')
        for t in w.task_list:
            logger.info(f'\t{t["sec_title"]} ({t["sec_time"] - t["start_loc"]}秒)')
    else:
        logger.info('没有找到课程，请先注册课程.')
        sys.exit(2)
    try:
        interval = 180  # 300 sec to update
        logger.info(f'开始，目标{go_minutes}分钟，同步间隔{interval}秒，按下 Ctrl+C 退出。')

        i = interval
        c = len(w.task_list)
        w.start_process_task(interval)
        cur_seconds = seconds
        sys.stdout.write('..')
        while c > 1:
            i -= 1
            if i < -10:
                cur_seconds = w.get_study_seconds(start_date=today)
                sys.stdout.write(f'\r时长: +{cur_seconds - seconds}秒  ')
                c = len(w.task_list)
                if c < 1:  # no task left
                    break
                i = interval
            else:
                sys.stdout.write(f'\r时长: +{cur_seconds - seconds}秒  ')

            sys.stdout.write('\b-')
            sys.stdout.flush()
            sleep(0.33)
            sys.stdout.write('\b\\')
            sys.stdout.flush()
            sleep(0.33)
            sys.stdout.write('\b/')
            sys.stdout.flush()
            sleep(0.34)
            cur_seconds += c

    except KeyboardInterrupt:
        w.stop_process_task()
    except Exception as ex:
        logger.error(ex)
        w.stop_process_task()
    finally:
        logger.debug('exit')
