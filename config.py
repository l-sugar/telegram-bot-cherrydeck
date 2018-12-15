# -*- coding: utf-8 -*-
import os

# CREDENTIALS
TOKEN = os.getenv('TG_TOKEN')  # restart the main script MANUALLY after this field is changed
ADMIN_PASSWORD = os.getenv('ADMIN_PW')  # to use special bot commands

# GROUPS
CHAT_GROUP = os.getenv('TG_CHAT_GROUP')

# INSTA_CREDENTIALS
INSTA_USERNAME = os.getenv('INSTA_USER')
INSTA_PASSWORD = os.getenv('INSTA_PW')

# TIMES
# ROUNDS_INTERVAL = 23 * 60 * 60  # interval between rounds, seconds
# DROP_WINDOW = 30 * 60  # drop window before each round_start, seconds
# ROUND_TIME = 1 * 60 * 60  # round_start time, seconds
# DROP_ANNOUNCE = 1 * 60 * 60 # drop_announcement time, seconds
# DROP_ENDS_SOON = DROP_WINDOW * 5 // 6 # drop_alert time

# TESTING TIMES
ROUNDS_INTERVAL = 1 * 3 * 60  # interval between rounds, seconds TESTING
DROP_WINDOW = 1 * 60  # drop window before each round_start, seconds TESTING
ROUND_TIME = 1 * 0.5 * 60  # round_start time, seconds TESTING
DROP_ANNOUNCE = 1 * 60 # drop_announcement time, seconds TESTING
DROP_ENDS_SOON = DROP_WINDOW * 4 // 5 # drop_alert time TESTING

BAD_USER_BAN_TIME = 15 * 24 * 60 * 60 # user ban time after bad behavior
# BAD_USER_BAN_TIME = 1 * 60 * 60 # user ban time after bad behavior TESTING

# PATH
CONFIG_NAME = 'config.py'  # this file's name
#FOLDER_PATH = '/home/Bot'  # this folder's full path
FOLDER_PATH = '/'  # this folder's full path

# DATABASE SETTINGS
DATABASE_URL = os.getenv('DATABASE_URL')

T_ROUND = {'NAME': 'round',
           'FIELDS':
               {
                   'STARTS_AT': 'starts_at',
                   'IS_FINISHED': 'is_finished',
                   'GROUP_ID': 'group_id',
                   'IN_PROGRESS': 'in_progress'
               }
           }
T_USER = {'NAME': 'participant',
          'FIELDS':
              {
                  'TG_NAME': 'tg_name',
                  'INSTA_LINK': 'insta_link',
                  'IS_BANNED': 'is_banned',
                  'BAN_WARNS': 'ban_warnings',
                  'USER_ID': 'user_id',
                  'FULL_NAME': 'full_name'
              }
          }
T_U_R = {'NAME': 'user_and_round',
         'FIELDS':
             {
                 'USER_ID': 'user_id',
                 'ROUND_ID': 'round_id'
             }
         }
