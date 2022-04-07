#!/usr/bin/python
import logging
import os
import ssl
import sys
import json
import subprocess
import sqlite3
import requests
import time
import yaml

# get current path
curr_dir = os.path.dirname(os.path.realpath(__file__))

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
            return data.decode('utf-8')
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
            # dataUsage = "Data Usage: " + str(round(item['value'] / (1024 * 1024 * 1024), 2)) + "GB"
            # print(round(item['value'] / (1024 * 1024 * 1024), 2))
            dataUsage = "Data Usage: " + handle_convert(item['value'])
        else:
            dataUsage = ""

        content = content + str(
            user + " \n" + trafficType + " \n" + dataUsage + "\n") + "----------------------------------------\n"
    return content


# send message to wechat
def send_message_to_wx(wechat_key, content):
    url = 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=' + wechat_key
    headers = {'content-type': 'application/json'}
    payload = {"msgtype": "text", "text": {"content": content.strip()}}
    payload = json.dumps(payload)
    r = requests.post(url, data=payload, headers=headers)
    logging.info(r)


# get bwg server info
def get_server_info(id, key):
    url = 'https://api.64clouds.com/v1/getServiceInfo?veid=' + id +'&api_key=' + key
    response = requests.get(url)
    response_json = response.json()
    if response_json['error'] != 0:
        logging.error('get bwg server info fail! reason:{}', response_json['message'])
        exit(1)

    total_flux = handle_convert(response_json['plan_monthly_data'])
    used_flux = handle_convert(response_json['data_counter'])
    next_reset_date = response_json['data_next_reset']
    reset_date = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(next_reset_date))

    return "----------------------------------------\n" + \
           "Total Flux: " + total_flux + "\n" \
           + "Used Flux: " + used_flux + "\n" \
           + "Reset Date: " + reset_date + "\n" \
           + "----------------------------------------\n"


if __name__ == '__main__':
    wx_key, bwg_id, bwg_key = get_config_info()
    xray_info = get_xray_info()
    server_info = get_server_info(bwg_id, bwg_key)
    print(server_info)
    result_content = get_result_content(xray_info, server_info)
    send_message_to_wx(wx_key, result_content)
    logging.info("Send message success!")
