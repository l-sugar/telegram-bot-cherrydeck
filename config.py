# -*- coding: utf-8 -*-
import os

# CREDENTIALS
TOKEN = process.env.TG_TOKEN  # restart the main script MANUALLY after this field is changed
ADMIN_PASSWORD = process.env.ADMIN_PW  # to use special bot commands

# GROUPS
CHAT_GROUP = process.env.TG_CHAT

# INSTA_CREDENTIALS
INSTA_USERNAME = process.env.INSTA_HANDLE
INSTA_PASSWORD = process.env.INSTA_PW

# TIMES
#ROUNDS_INTERVAL = 5 * 60 * 60  # interval between rounds, seconds
#DROP_WINDOW = 30 * 60  # drop window before each round_start, seconds
#ROUND_TIME = 1 * 60 * 60  # round_start time, seconds

# TESTING TIMES
ROUNDS_INTERVAL = 1 * 0.5 * 60  # interval between rounds, seconds TESTING
DROP_WINDOW = 0.5 * 60  # drop window before each round_start, seconds TESTING
ROUND_TIME = 1 * 0.1 * 60  # round_start time, seconds TESTING

#BAD_USER_BAN_TIME = 360 * 60 * 60 # user ban time after bad behavior
BAD_USER_BAN_TIME = 1 * 4 * 60 # user ban time after bad behavior TESTING

# PATH
CONFIG_NAME = 'config.py'  # this file's name
#FOLDER_PATH = '/home/Bot'  # this folder's full path
FOLDER_PATH = '/'  # this folder's full path

# DATABASE SETTINGS
DB_NAME = 'bot_base.db'  # full database's path
T_ROUND = {'NAME': 'round',
           'FIELDS':
               {
                   'STARTS_AT': 'starts_at',
                   'IS_FINISHED': 'is_finished',
                   'GROUP_ID': 'group_id'
               }
           }
T_USER = {'NAME': 'user',
          'FIELDS':
              {
                  'TG_NAME': 'tg_name',
                  'INSTA_LINK': 'insta_link',
                  'IS_BANNED': 'is_banned',
                  'BAN_WARNS': 'ban_warnings',
                  'USER_ID': 'user_id',
                  'IS_P': 'is_pidoras'
              }
          }
T_U_R = {'NAME': 'user_and_round',
         'FIELDS':
             {
                 'USER_ID': 'user_id',
                 'ROUND_ID': 'round_id'
             }
         }
