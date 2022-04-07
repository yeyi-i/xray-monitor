#!/usr/bin/python

import os
import sys
import json
import subprocess
import sqlite3
import requests
import time

if sys.version_info < (3,7):

    def getProcessOutput(cmd):
        process = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE
        )
        process.wait()
        data, err = process.communicate()

        if process.returncode is 0:
            return data.decode('utf-8')
        else:
            print("Error: ", err)
            return None

elif sys.version_info >= (3,7):
    print("Not compatiable for 3.7 or newer yet")
    exit(1)

Result_Data = getProcessOutput('/usr/local/bin/xray api statsquery --server=localhost:10085')

content = ""
content = content + str(time.strftime('%Y-%m-%d %H:%M', time.localtime())) + "\n"

if Result_Data is not None:
    for item in json.loads(Result_Data)['stat']:
        user = "User Name: " + item['name'].split('>>>')[1]
        #print(item['name'].split('>>>')[1])
        trafficType = "Traffic Type: " + item['name'].split('>>>')[3]
        #print(item['name'].split('>>>')[3])
        if 'value' in item:
            dataUsage = "Data Usage: " + str(round(item['value'] / (1024 * 1024 * 1024), 2)) + "GB"
            #print(round(item['value'] / (1024 * 1024 * 1024), 2))
        else:
            dataUsage = ""
        
        content = content + str(user + " \n" + trafficType + " \n" + dataUsage + "\n") + "----------------------------------------\n"

        #print(item['name'].split('>>>')[1])
    #print(json.loads(Result_Data)['stat'])



url = 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key='
headers = {'content-type': 'application/json'}
payload = {"msgtype": "text", "text": {"content": content.strip()}}
payload = json.dumps(payload)

r = requests.post(url, data=payload, headers=headers)

print(r)
