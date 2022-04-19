#!/usr/bin/python
import base64
import datetime
import hashlib
import logging
import os
import random
import sys
import json
import subprocess
import sqlite3
import requests
import time
import yaml
from dateutil.relativedelta import relativedelta
import matplotlib.pyplot as plt
from apscheduler.schedulers.blocking import BlockingScheduler

# get current path
curr_dir = os.getcwd()
print(curr_dir)
wx_key = ''
bwg_id = 0
bwg_key = ''

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(pathname)s[line:%(lineno)d] - %(levelname)s: %(message)s',
    datefmt='%y-%m-%d %H:%M',
    filename=curr_dir + os.sep + "xray-monitor.log",
    filemode='a')


# convert bytes to KB MB GB
def handle_convert(value):
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    size = 1024.0
    for i in range(len(units)):
        if (value / size) < 1:
            return "%.2f%s" % (value, units[i])
        value = value / size


# get xray info string
def get_xray_info():
    cmd = '/usr/local/bin/xray api statsquery --server=localhost:10085'
    if sys.version_info < (3, 7):
        process = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE
        )
        process.wait()
        data, err = process.communicate()

        if process.returncode == 0:
            xrayInfos = []
            jsonArray = json.loads(data.decode('utf-8'))
            for i in range(len(jsonArray["stat"])):
                xrayInfo = {}
                jsonObject = jsonArray['stat'][i]
                nameList = jsonObject['name'].split(">>>")
                xrayInfo.setdefault('name', nameList[1])
                xrayInfo.setdefault('type', nameList[3])
                xrayInfo.setdefault('flux', int(jsonObject['value']))
                xrayInfos.append(xrayInfo)
            return xrayInfos
        else:
            logging.error(err)
            return None
    elif sys.version_info >= (3, 7):
        logging.error("Not compatiable for 3.7 or newer yet")
        exit(1)


# get config info
def get_config_info():
    # get config path
    config_file = curr_dir + os.sep + "config.yml"

    f = open(config_file, 'r', encoding='utf-8')
    data = yaml.load(f, Loader=yaml.FullLoader)
    # check config
    if "xray" not in data:
        logging.error("can't find xray in config")
        exit(1)
    xray = data["xray"]
    if "wx-key" not in xray:
        logging.error("can't find wx-key in config")
        exit(1)
    if "bwg-id" not in xray:
        logging.error("can't find bwg-id in config")
        exit(1)
    if "bwg-key" not in xray:
        logging.error("can't find bwg-key in config")
        exit(1)
    return xray["wx-key"], xray["bwg-id"], xray["bwg-key"]


# get xray api result to output string
def get_result_content(xray_result, server_result):
    if xray_result is None:
        logging.error("xray result in null")
        exit(1)

    content = "Current Date: " + str(time.strftime('%Y-%m-%d %H:%M', time.localtime())) + "\n" + server_result
    for item in json.loads(xray_result)['stat']:
        user = "User Name: " + item['name'].split('>>>')[1]
        # print(item['name'].split('>>>')[1])
        trafficType = "Traffic Type: " + item['name'].split('>>>')[3]
        # print(item['name'].split('>>>')[3])
        if 'value' in item:
            dataUsage = "Data Usage: " + handle_convert(item['value'])
        else:
            dataUsage = ""

        content = content + str(
            user + " \n" + trafficType + " \n" + dataUsage + "\n") + "----------------------------------------\n"
    return content


# send message to wechat
def send_message_to_wx(content):
    url = 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=' + wx_key
    headers = {'content-type': 'application/json'}
    payload = {"msgtype": "text", "text": {"content": content.strip()}}
    payload = json.dumps(payload)
    r = requests.post(url, data=payload, headers=headers)
    logging.info(r)


# send message to wechat
def send_picture_to_wx(wechat_key, pic_md5, pic_base64):
    url = 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=' + wechat_key
    headers = {'content-type': 'application/json'}
    payload = {"msgtype": "image", "image": {"base64": pic_base64, "md5": pic_md5}}
    payload = json.dumps(payload)
    r = requests.post(url, data=payload, headers=headers)
    logging.info(r)


# get bwg server info
def get_server_info(vid, key):
    url = 'https://api.64clouds.com/v1/getServiceInfo?veid=' + str(vid) + '&api_key=' + key
    response = requests.get(url)
    response_json = response.json()
    if response_json['error'] != 0:
        msg = response_json['message']
        logging.error('get bwg server info fail! reason:' + msg)
        send_message_to_wx('get bwg server info fail! reason:' + msg)
        exit(1)

    total_flux = handle_convert(response_json['plan_monthly_data'])
    used_flux = handle_convert(response_json['data_counter'])
    next_reset_date = response_json['data_next_reset']

    logging.info("Total Flux: " + total_flux + ", Used Flux: " + used_flux + ", Reset Date: " + str(next_reset_date))
    return total_flux, used_flux, next_reset_date


# get database connection
def db_conn():
    db_path = curr_dir + os.sep + 'db/'
    if not os.path.exists(db_path):
        os.mkdir(db_path)
    return sqlite3.connect(db_path + 'xray.db')


# close database connection
def db_close(connect):
    connect.close()


# init database first time
def init_database():
    conn = db_conn()
    cursor = conn.cursor()

    # user data
    create_xray_user_sql = '''create table if not exists xray_user (
        id integer primary key autoincrement not null,
        name text,
        type text,
        flux int,
        init_flux int,
        create_time int);'''
    cursor.execute(create_xray_user_sql)

    # server reset data
    create_reset_sql = '''create table if not exists xray_reset (
        reset_date int,
        next_reset_date int);'''
    cursor.execute(create_reset_sql)
    conn.close()


# insert user used into database
def insert_user_info(infos):
    conn = db_conn()
    cursor = conn.cursor()

    for info in infos:
        cursor.execute('insert into xray_user (name, type, flux, init_flux, create_time) '
                       'values (?, ?, ?, ?, ?)', (info['name'],
                                                  info['type'],
                                                  str(info['flux']),
                                                  str(info['init_flux']),
                                                  int(time.mktime(datetime.datetime.now().timetuple()))))

    conn.commit()
    conn.close()


def query_user_info(reset_time, flux_type):
    conn = db_conn()
    cursor = conn.cursor()
    last_reset_datetime = timestamp_to_datetime(reset_time) + relativedelta(months=-1)
    last_reset_time = int(time.mktime(last_reset_datetime.timetuple()))
    select_user_info_sql = 'select name, ' \
                           'type, ' \
                           'max(flux - ifnull(init_flux, 0))/1000/1000 flux, ' \
                           'strftime(\'%Y-%m-%d\',date(create_time, \'unixepoch\', \'localtime\')) create_time ' \
                           'from xray_user where create_time >= ' \
                           + str(last_reset_time) \
                           + ' and create_time <' + str(reset_time) + ' and type = \'' + flux_type + '\'' \
                           + ' group by name, type, strftime(\'%Y-%m-%d\',date(create_time, \'unixepoch\', \'localtime\'))' \
                             ' order by name desc, create_time asc'
    execute_result = cursor.execute(select_user_info_sql)
    print(execute_result)
    # draw viewer
    plot_dict = {}
    for row in execute_result:
        print(row)
        name = row[0]
        name_info = plot_dict.get(name)
        if name_info is None:
            name_info = {}
        x = name_info.get('x')
        if x is None:
            x = []
        y = name_info.get('y')
        if y is None:
            y = []
        x.append(row[3])
        y.append(row[2])
        name_info.setdefault('x', x)
        name_info.setdefault('y', y)
        plot_dict.setdefault(name, name_info)
    conn.close()
    return plot_dict


# random plot color
def get_random_color():
    colorArr = ['1', '2', '3', '4', '5', '6', '7', '8', '9', 'A', 'B', 'C', 'D', 'E', 'F']
    color = ""
    for i in range(6):
        color += colorArr[random.randint(0, 14)]
    return "#" + color


# generate plot data from query result
def random_line_style():
    line_style = ['-', '--', '-.', ':']
    return line_style[random.randint(0, len(line_style) - 1)]


def generate_plot_data(plot_dict, flux_type):
    plt.figure()
    tmp_path = 'tmp'
    if not os.path.exists(tmp_path):
        os.mkdir(tmp_path)
    for key in plot_dict.keys():
        info = plot_dict.get(key)
        x = info['x']
        y = info['y']
        plt.plot(x, y, color=get_random_color(), linestyle=random_line_style(), label=key)
        plt.legend()
    plt.xlabel('date', fontsize=20)
    plt.ylabel('flux', fontsize=20)
    plt.title(flux_type + ' statistical graph')
    save_path = tmp_path + os.sep + flux_type + '.png'
    plt.savefig(save_path)
    plt.close()
    return get_picture_md5_and_base64(save_path)


# get local picture and covert to base64
def get_picture_md5_and_base64(pic_path):
    with open(pic_path, 'rb') as img:
        content = img.read()
        return hashlib.md5(content).hexdigest(), str(base64.b64encode(content), encoding='utf-8')


# get time by timestamp and timezone
def timestamp_to_datetime(timestamp):
    return datetime.datetime.fromtimestamp(timestamp)


# query xray server info from database
def query_xray_reset():
    conn = db_conn()
    cursor = conn.cursor()
    query_sql = '''select reset_date, next_reset_date from xray_reset;'''
    cursor.execute(query_sql)
    result_data = cursor.fetchone()
    conn.close()
    if result_data is None:
        return None
    else:
        return {'reset_date': result_data[0], 'next_reset_date': result_data[1]}


# insert xray server info to database
def inset_xray_reset(reset_date_timestamp, next_reset_date):
    conn = db_conn()
    cursor = conn.cursor()
    cursor.execute('delete from xray_reset')
    cursor.execute('insert into xray_reset (reset_date, next_reset_date) '
                   'values (?, ?)', (reset_date_timestamp, next_reset_date))

    conn.commit()
    conn.close()


# init xray reset when run first time or data is expired
def init_xray_reset():
    query_result = query_xray_reset()
    # first time to get data or data is expired
    if query_result is None or query_result['next_reset_date'] < int(time.mktime(datetime.datetime.now().timetuple())):
        _, _, reset_date_timestamp = get_server_info(bwg_id, bwg_key)
        next_reset_date = timestamp_to_datetime(reset_date_timestamp) + relativedelta(months=1)
        next_reset_date_timestamp = int(time.mktime(next_reset_date.timetuple()))
        inset_xray_reset(reset_date_timestamp, next_reset_date_timestamp)
        return reset_date_timestamp
    return query_result['reset_date']


# get plot picture and send message to bot
def send_server_info_and_user_data():
    logging.info('get server info and send wx start...')
    down = 'downlink'
    up = 'uplink'
    reset_date = init_xray_reset()
    logging.info('get server info and send picture start...')
    down_md5, down_bas64 = generate_plot_data(query_user_info(reset_date, down), down)
    up_md5, up_bas64 = generate_plot_data(query_user_info(reset_date, up), up)
    send_picture_to_wx(wx_key, down_md5, down_bas64)
    send_picture_to_wx(wx_key, up_md5, up_bas64)
    logging.info('get server info and send picture end...')
    total_flux, used_flux, new_reset_date = get_server_info(bwg_id, bwg_key)
    # reset date
    if new_reset_date != reset_date:
        next_reset_date = timestamp_to_datetime(reset_date) + relativedelta(months=1)
        next_reset_date_timestamp = int(time.mktime(next_reset_date.timetuple()))
        inset_xray_reset(new_reset_date, next_reset_date_timestamp)

    reset_date_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(new_reset_date))

    content = "Current Date: " + str(time.strftime('%Y-%m-%d %H:%M', time.localtime())) + "\n" \
              + '----------------------------------------\n' \
              + "Total Flux: " + total_flux + ",\nUsed Flux: " + used_flux + ",\nReset Date: " + reset_date_str
    logging.info('sending statistical data...')
    send_message_to_wx(content)
    logging.info('get server info and send wx end...')


# get user last reset date max flux
def get_last_reset_date_user_info(name, flux_type, reset_date_timestamp):
    conn = db_conn()
    cursor = conn.cursor()
    last_reset_date = timestamp_to_datetime(reset_date_timestamp) - relativedelta(months=1)
    last_reset_date_timestamp = int(time.mktime(last_reset_date.timetuple()))
    cursor.execute('select ifnull(max(flux),0) from xray_user where name=\''
                   + name
                   + '\' and create_time <='
                   + str(last_reset_date_timestamp)
                   + ' and type=\'' + flux_type + '\'')
    result_data = cursor.fetchone()

    conn.close()
    return result_data[0]


# record xray user info to database
def record_xray_user_info(infos, reset_date_timestamp):
    for info in infos:
        init_flux = get_last_reset_date_user_info(info['name'], info['type'], reset_date_timestamp)
        info.setdefault('init_flux', init_flux)
    insert_user_info(infos)


# get xray user info from api and record to database
def get_and_record_xray_user_info():
    reset_date = init_xray_reset()
    xray_infos = get_xray_info()
    logging.info('record user flux info start...')
    record_xray_user_info(xray_infos, reset_date)
    logging.info('record user flux info end...')


if __name__ == '__main__':
    # start running
    wx_key, bwg_id, bwg_key = get_config_info()
    init_database()
    # reset_date = init_xray_reset()
    logging.info('xray-monitor is running...')

    schedule = BlockingScheduler()
    # generate picture per 5 minutes
    schedule.add_job(send_server_info_and_user_data, 'interval', hours=12)
    schedule.add_job(get_and_record_xray_user_info, 'interval', minutes=1)
    logging.info("schedule is setting up!")
    schedule.start()
