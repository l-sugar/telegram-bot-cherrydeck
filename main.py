# -*- coding: utf-8 -*-
import logging
import re
import sqlite3
import psycopg2
import psycopg2.extras

from datetime import datetime, timedelta
from threading import Thread
from time import sleep

from InstagramAPI import InstagramAPI
from telegram.ext import CommandHandler, MessageHandler, Updater, Filters

import texts
from config import *

# TODO если надо будет обновлять конфиг в лайве
# import importlib
# import pyinotify

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

sleep_time = 0.25
insta_user_pattern = re.compile(r'^([hH]ttp)?s?(://)?([wW]ww.)?[iI]nstagram.com/[^/][^p/].*?/?$')

times = {}  # {group_tg_id: closest round_start start timestamp}


# TODO если надо будет обновлять конфиг в лайве
# class Identity(pyinotify.ProcessEvent):
#     def process_default(self, event):
#         if event.name.lower() == CONFIG_NAME.lower():
#             logger.info('Config has been modified')
#             importlib.reload(config)
#             logger.info('Config has been reloaded')


def async1(f):
    def wrapper(*args, **kwargs):
        thr = Thread(target=f, args=args, kwargs=kwargs)
        thr.start()

    return wrapper


def error(bot, update, error):
    logger.warning('Update "%s" caused error "%s"' % (update, error))


# the bot has to be an admin to receive group messages
@async1
def echo(bot, update):
    global times

    text = update.message.text.strip()
    logging.info('Received: {}'.format(text))
    if not re.match(insta_user_pattern, text):
        if is_admin(bot, update.message.from_user.id, update.message.chat_id):
            logger.info("{}'s (admin) message has been passed".format(update.message.from_user.id))
        else:
            bot.delete_message(chat_id=update.message.chat.id, message_id=update.message.message_id)
            logger.info('Message has been deleted: {}'.format(text))
            bot.sendMessage(update.message.chat.id, texts.MESSAGE_DELETED + CHAT_GROUP, disable_web_page_preview=True)
    else:
        if update.message.chat_id not in times:
            added = add_to_times(update.message.chat_id)  # adds next round_start start time to the dict
            if not added:
                bot.sendMessage(update.message.chat.id, texts.CANT_FIND_NEXT_ROUND)
                return

        start = datetime.fromtimestamp(times[update.message.chat_id]) - timedelta(seconds=DROP_WINDOW)  # window start
        end = datetime.fromtimestamp(times[update.message.chat_id])  # drop window end
        now = datetime.now()

        logger.info(f'start: {start}, now: {now}, end: {end}')
        if start < now < end:
            if update.message.from_user.username:
                add_to_next_round(update.message.from_user.username, update.message.chat.id, text,
                                  update.message.from_user.id, update.message.from_user.full_name)
            else:
                add_to_next_round('', update.message.chat.id, text,
                                  update.message.from_user.id, update.message.from_user.full_name)
            #bot.sendMessage(update.message.chat_id, texts.LINK_ADDED)

        else:
            bot.delete_message(chat_id=update.message.chat.id, message_id=update.message.message_id)
            logger.info('Wrong time. Message has been deleted: {}'.format(text))


def usernames_from_links(arr):
    res = []
    for i in arr:
        if not i:
            continue
        #i = re.search(r'nstagram.com/*+/?', i)
        # if i.find("?") >= 1:
        #     i = i.rsplit('?', maxsplit=1)[-1]
        match = re.search('nstagram.com/[^/?]+', i)
        # if i[-1] == '/':
        #     i = i[:-1]
        username = match.group().rsplit('/', maxsplit=1)[-1]
        res.append(username)
    return res

def handle_from_link(link):
    match = re.search('nstagram.com/[^/?]+', link)
    username = match.group().rsplit('/', maxsplit=1)[-1]
    return username

# @async1
def add_to_next_round(tg_name, chatid, insta_link, userid, fullname):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()
    cursor.execute(f'''SELECT * from {T_USER['NAME']} where {T_USER['FIELDS']['USER_ID']}=%s''', (userid,))
    data = cursor.fetchall()
    if not data:  # если пользователя нет в таблице users, добавляем
        query = f'''INSERT INTO {T_USER['NAME']} ({T_USER['FIELDS']['TG_NAME']}, {T_USER['FIELDS']['INSTA_LINK']}, \
        {T_USER['FIELDS']['USER_ID']}, {T_USER['FIELDS']['FULL_NAME']}) VALUES (%s, %s, %s, %s)'''
        cursor.execute(query, (tg_name, insta_link, userid, fullname))
        conn.commit()
        logger.info(f'{insta_link} inserted')
    else:  # если есть - обновляем ссылку на инсту
        query = f'''UPDATE {T_USER['NAME']} SET {T_USER['FIELDS']['INSTA_LINK']}=%s, {T_USER['FIELDS']['FULL_NAME']}=%s \
                                            WHERE {T_USER['FIELDS']['USER_ID']}=%s'''
        cursor.execute(query, (insta_link, fullname, userid))
        conn.commit()
        logger.info(f'{insta_link} changed')

    query = f'''SELECT * from {T_U_R['NAME']} WHERE {T_U_R['FIELDS']['USER_ID']}\
    =(SELECT id from {T_USER['NAME']} where {T_USER['FIELDS']['FULL_NAME']}=%s LIMIT 1)\
    AND {T_U_R['FIELDS']['ROUND_ID']}\
    =(SELECT id from {T_ROUND['NAME']} WHERE {T_ROUND['FIELDS']['GROUP_ID']}=%s \
    AND {T_ROUND['FIELDS']['IS_FINISHED']}=False ORDER BY id ASC LIMIT 1)'''
    cursor.execute(query, (fullname, chatid))
    data = cursor.fetchall()
    if not data:  # если пользователь не связан с раундом
        query = f'''INSERT INTO {T_U_R['NAME']} VALUES ((select id from {T_USER['NAME']} \
        where {T_USER['FIELDS']['USER_ID']}=%s ORDER BY id asc limit 1), \
        (SELECT id from {T_ROUND['NAME']} WHERE {T_ROUND['FIELDS']['GROUP_ID']}=%s \
        AND {T_ROUND['FIELDS']['IS_FINISHED']}=False ORDER BY id ASC LIMIT 1))'''
        cursor.execute(query, (userid, chatid))  # creates new round_start
        conn.commit()
        logger.info('Record added')
    conn.close()


def get_next_start_time(chatid):
    dt_now = datetime.now().timestamp()

    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()
    query = f'''SELECT {T_ROUND['FIELDS']['STARTS_AT']} from {T_ROUND['NAME']} WHERE {T_ROUND['FIELDS']['GROUP_ID']}=%s \
    AND {T_ROUND['FIELDS']['IS_FINISHED']}=False and {T_ROUND['FIELDS']['STARTS_AT']}>{dt_now} ORDER BY id ASC LIMIT 1'''
    cursor.execute(query, (chatid,))
    data = cursor.fetchall()
    conn.close()
    if data:
        return data[0][0]
    return None


@async1
def add_to_times(chatid):
    global times
    data = get_next_start_time(chatid)
    logger.info(f'Adding to times: {chatid}')
    # print(data)
    if data:
        # print(data)
        times[chatid] = data
        logger.warning(f'Times: {times}')
        return data
    return None


def getComments(api, post_id):
    next_max_id = True
    comments = []
    while next_max_id:
        try:
            if next_max_id is True:
                next_max_id = ''
            _ = api.getMediaComments(post_id, max_id=next_max_id)
            for i in api.LastJson['comments']:
                try:
                    commentator = i.get('user', "").get('username', "")
                    comments.append(commentator)
                except:
                    pass
            sleep(sleep_time)
            next_max_id = api.LastJson.get('next_max_id', '')
        except Exception as e:
            logger.exception(e)
    return comments


def gather(api, userList):
    global_mas = []
    likers = []
    try:
        for user in userList:
            try:
                tmp = []
                api.searchUsername(user)
                id = str(api.LastJson.get('user', "").get("pk", ""))
                api.getUserFeed(id)
                post_id = str(api.LastJson.get('items', "")[0].get("pk", ""))
                api.getMediaLikers(post_id)
                for i in api.LastJson['users']:
                    likers.append(i.get('username', ""))
                user_comments = getComments(api, post_id)
                tmp.append(likers)
                tmp.append(user_comments)
                global_mas.append(tmp)
                sleep(1.75)
            except Exception as e:
                logger.exception(e)

        return global_mas

    except Exception as e:
        logger.exception(e)
        return None


def check(res, users):
    approved = []
    try:
        for _, i in enumerate(users):
            if all(i in res[x][0] for x in range(len(res)) if x != _) and all(
                    i in res[x][1] for x in range(len(res)) if x != _):
                approved.append(i)
        return approved

    except Exception as e:
        logger.exception(e)
        return None


# def new_user_welcome(bot, update):
#     for i in update.message.new_chat_members:
#         bot.restrict_chat_member(chat_id=update.message.chat.id, user_id=i.id, can_send_messages=True,
#                                  can_add_web_page_previews=False)
#         logger.info('User {} has been restricted from send web page previews'.format(i.id))
#         bot.sendMessage(update.message.chat.id, 'Hi @' + str(i.username) + texts.WELCOME, disable_web_page_preview=True)
#         logger.info('Welcome message sent')


def is_admin(bot, userid, chatid):
    admins = [admin.user.id for admin in bot.get_chat_administrators(chatid)]
    return userid in admins


# @async1
def new_group_setup(bot, update, args, job_queue):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()

    cursor.execute(f'''select * from {T_ROUND['NAME']} \
                    WHERE {T_ROUND['FIELDS']['IN_PROGRESS']}=True and {T_ROUND['FIELDS']['GROUP_ID']} = {update.message.chat.id}''')
    data = cursor.fetchall()
    conn.close()
    if data:
        bot.sendMessage(update.message.chat.id, texts.ROUND_ALREADY_SET)
        logger.info("There's a round for this group in progress right now")
        return
    else:
        logger.warning('/setup ' + str(args))
        if not args:
            bot.sendMessage(update.message.chat.id, texts.SETUP_MISSING_TIME)
            return

        if not is_admin(bot, update.message.from_user.id, update.message.chat_id):
            bot.sendMessage(update.message.chat.id, texts.PERMISSION_ERROR)
            return

        time = args[0]
        try:
            tomorrow = False
            dt = datetime.strptime(time, "%H:%M")
            if len(args) == 2:
                if args[1].lower() == 'tomorrow':
                    tomorrow = True
            dt_now = datetime.now()
            dt = dt.replace(year=dt_now.year, month=dt_now.month, day=dt_now.day)
            if tomorrow:
                dt = dt + timedelta(days=1)

            if dt < datetime.now() + timedelta(seconds=DROP_WINDOW):
                raise Exception
        except Exception as e:
            logger.exception(e)
            bot.sendMessage(update.message.chat.id, texts.BAD_TIME_FORMAT)
        else:
            next_round_starts = dt.timestamp()

            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            cursor = conn.cursor()

            dt_now = datetime.now().timestamp()
            cursor.execute(f'''select * from {T_ROUND['NAME']} where {T_ROUND['FIELDS']['STARTS_AT']}>{dt_now} \
            and {T_ROUND['FIELDS']['GROUP_ID']}={update.message.chat_id}''')
            data = cursor.fetchall()
            if not data:
                query = f'''INSERT INTO {T_ROUND['NAME']} ({T_ROUND['FIELDS']['STARTS_AT']}, \
                {T_ROUND['FIELDS']['GROUP_ID']}) VALUES (%s, %s)'''
                cursor.execute(query, (next_round_starts, update.message.chat_id))  # creates new round_start
                conn.commit()
                #bot.sendMessage(update.message.chat.id, texts.SETUP_SUCCESS)
                logger.info(f'New round set to {args}')

                plan_all_round_jobs(job_queue)
                jobs = job_queue.jobs()
                for i in jobs:
                    logger.warning(f'Job planned: {i.name}')
            else:
                bot.sendMessage(update.message.chat.id, texts.ROUND_ALREADY_SET)
                logger.info("There's a round for this group in the future")
            conn.close()

def drop_window(bot, job):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()

    dt_now = datetime.now().timestamp()
    chatid = job.context[0]
    job_queue = job.context[1]

    cursor.execute(f'''update {T_ROUND['NAME']} SET {T_ROUND['FIELDS']['IN_PROGRESS']}=True \
    WHERE id IN (SELECT id FROM {T_ROUND['NAME']} WHERE {T_ROUND['FIELDS']['STARTS_AT']} > {dt_now} \
    AND {T_ROUND['FIELDS']['GROUP_ID']} = {job.context[0]} ORDER BY id ASC LIMIT 1)''')
    conn.commit()
    conn.close()

    logger.warning('Drop window started')
    bot.sendMessage(chatid, texts.GIMME_UR_LINKS, disable_web_page_preview=True)
    logger.info(f'Drop window started: {job.context[0]}')

    job_queue.run_once(drop_alert, (DROP_ENDS_SOON), context=chatid, name='plan drop_alert')
    jobs = job_queue.jobs()
    for i in jobs:
        logger.warning(f'Job planned: {i.name}')


@async1
def drop_alert(bot, job):
    bot.sendMessage(job.context, texts.DROP_ALMOST_OVER)
    logger.warning('drop_alert sent')

def drop_soon_announce(bot, job):
    chatid = job.context
    bot.sendMessage(chatid, texts.DROP_SOON)
    logger.warning(f'Drop announcement sent for group {chatid}')

def check_instagram(api, lst):
    logger.info('Checking Instagram...')
    result = gather(api, lst)
    approved = check(result, lst)
    res = list(set(lst) - set(approved))
    logger.info(res)
    return res


@async1
def check45(bot, job):
    logger.warning('45 mins check')
    chatid = job.context[0]
    nicks = job.context[1]

    pidorases = check_instagram(api, nicks)
    if not pidorases:
        logging.info('check45: All users had liked&commented each other')
    else:
        logging.info(f"These users did not complete the requirements: {pidorases}")
        lst = [x for x in get_bad_users(pidorases)]
        list_to_send = '\n'.join(lst)
        logger.info(f'These users did not complete the requirements: {lst}')
        bot.sendMessage(chatid, texts.BAD_CONDITIONS + list_to_send)


def final_check(bot, job):
    chatid = job.context[0]
    nicks = job.context[1]
    job_queue = job.context[2]
    logger.warning('Final check')

    pidorases = check_instagram(api, nicks)
    if not pidorases:
        logging.info('All users have liked&commented each other')
        #bot.sendMessage(chatid, texts.ROUND_SUCCESS)
    else:
        lst = [x for x in get_bad_users(pidorases)]
        list_to_send = '\n'.join(lst)
        bot.sendMessage(chatid, texts.BAD_USERS + list_to_send + texts.BAD_BEHAVIOR_INFO)

    goods = list(set(nicks) - set(pidorases))
    check_if_bans_necessary(goods, pidorases, chatid, bot)
    mark_as_pidorases(pidorases)

    end_and_plan_next(bot, [chatid, job_queue])

def announce_round_finish(bot, chatid):
    bot.sendMessage(chatid, texts.ROUND_FINISHED)
    bot.sendMessage(chatid, f'Next Drop starts in {timedelta(seconds=ROUNDS_INTERVAL) - timedelta(seconds=DROP_WINDOW)}')


def check_if_bans_necessary(g, p, chatid, bot):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()
    for i in p:
        cursor.execute(f'''select {T_USER['FIELDS']['USER_ID']} from {T_USER['NAME']} \
        where {T_USER['FIELDS']['BAN_WARNS']}=2 and {T_USER['FIELDS']['INSTA_LINK']} like %s''', (f'%{i}%',))
        data = cursor.fetchone()
        if data:
            print(f'user has reached ban limit:', data[0])
            if is_admin(bot, data[0], chatid):
                logger.warning('Cannot restrict admin')
            else:
                ban(bot, data[0], chatid)
                cursor.execute(f'''UPDATE {T_USER['NAME']} SET {T_USER['FIELDS']['BAN_WARNS']}=0 \
                WHERE {T_USER['FIELDS']['USER_ID']}={data[0]}''')
                conn.commit()
    conn.close()


def mark_as_pidorases(lst):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()
    for i in lst:
        cursor.execute(f'''update {T_USER['NAME']} set {T_USER['FIELDS']['BAN_WARNS']}=({T_USER['FIELDS']['BAN_WARNS']}+1)
         where {T_USER['FIELDS']['INSTA_LINK']} like %s''', (f'%{i}%',))
        logger.warning(f'{i} BAN_WARNS + 1')
    conn.commit()
    conn.close()


@async1
def ban(bot, userid, chatid):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()

    cursor.execute (f'''select {T_USER['FIELDS']['FULL_NAME']} from {T_USER['NAME']} \
    where {T_USER['FIELDS']['USER_ID']} = %s''', (userid,))
    user_name = cursor.fetchone()
    conn.close()

    bot.restrict_chat_member(chatid, userid, until_date = (datetime.now() + timedelta(seconds=BAD_USER_BAN_TIME)).timestamp(), can_send_messages = False)
    logger.warning(f'{userid} id has been restricted from posting for 15 days')
    bot.sendMessage(chatid, ''.join(user_name) + texts.BANNED)

def get_bad_users(usrs):
    res = list()
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()
    for i in usrs:
        cursor.execute(f'''select distinct {T_USER['FIELDS']['FULL_NAME']} from {T_USER['NAME']} \
        WHERE {T_USER['FIELDS']['INSTA_LINK']} like %s''', (f'%{i}%',))
        data = cursor.fetchone()
        if data:
            res.append(data[0])
    conn.close()
    return res


def end_and_plan_next(bot, cont):
    chatid = cont[0]
    job_queue = cont[1]
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()


    cursor.execute(f'''update {T_ROUND['NAME']} \
    set {T_ROUND['FIELDS']['IS_FINISHED']}=True, {T_ROUND['FIELDS']['IN_PROGRESS']}=False where \
    {T_ROUND['FIELDS']['IS_FINISHED']}=False and {T_ROUND['FIELDS']['STARTS_AT']}={times[chatid]}''')
    conn.commit()
    logger.info('Round has ended')
    jobs = job_queue.jobs()
    for i in jobs:
        logger.warning(f'Job planned: {i.name}')

    next_start_time = (datetime.now() + timedelta(seconds=ROUNDS_INTERVAL)).timestamp()

    cursor.execute(f'''UPDATE {T_USER['NAME']} set {T_USER['FIELDS']['INSTA_LINK']} = NULL \
    WHERE id in (select distinct {T_U_R['FIELDS']['USER_ID']} from {T_U_R['NAME']} \
    where {T_U_R['FIELDS']['ROUND_ID']} in (select distinct id from {T_ROUND['NAME']} \
    where {T_ROUND['FIELDS']['IS_FINISHED']}=True and {T_ROUND['FIELDS']['GROUP_ID']}={chatid}))''')
    conn.commit()

    query = f'''INSERT INTO {T_ROUND['NAME']} ({T_ROUND['FIELDS']['STARTS_AT']}, \
    {T_ROUND['FIELDS']['GROUP_ID']}) VALUES (%s, %s)'''
    cursor.execute(query, (next_start_time, chatid))  # creates new round_start
    conn.commit()
    conn.close()

    logger.info(f'New round set to {datetime.fromtimestamp(next_start_time)}')
    plan_all_round_jobs(job_queue)
    announce_round_finish(bot, chatid)


# @async1
def round_start(bot, job):
    # job.context[1] = job_queue
    logger.warning('Round started')
    t = times[job.context[0]]
    logger.warning(f'Time: {t}')
    links = get_round_links(t)

    if links:
        links = [x[0] for x in links]

    if not links:
        logger.warning('No links for this round')
        bot.sendMessage(job.context[0], texts.NO_USERS_PARTICIPATE)
        end_and_plan_next(bot, job.context)
    elif len(links) == 1:
        logger.warning('Not enough users for the round')
        bot.sendMessage(job.context[0], texts.USER_SO_ALONE)
        end_and_plan_next(bot, job.context)

    else:  # plan 45min alert
        nicknames = usernames_from_links(links)
        logger.info(f'nicknames: {nicknames}, links: {links}')
        bot.sendMessage(job.context[0], texts.ROUND_STARTED)
        links_list = '\n\n'.join(links)
        logger.info(f'Links for this round ({job.context[0]}): {links_list}')
        bot.sendMessage(job.context[0], links_list, disable_web_page_preview=True)
        bot.sendMessage(job.context[0], texts.ROUND_START_RULES)
        job.context[1].run_once(check45, (ROUND_TIME // 4) * 3, context=[job.context[0], nicknames],
                                name=f'45min alert for {job.context[0]}')
        job.context[1].run_once(final_check, ROUND_TIME, context=[job.context[0], nicknames, job.context[1]],
                                name=f'final checking for {job.context[0]}')
        logger.info(f'Checkings planned: {job.context[1].jobs()}')
        jobs = job.context[1].jobs()
        for i in jobs:
            logger.warning(f'Job planned: {i.name}')


def get_round_links(time):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()
    cursor.execute(f'''select {T_USER['FIELDS']['INSTA_LINK']} from {T_USER['NAME']} \
    where id in (select {T_U_R['FIELDS']['USER_ID']} from {T_U_R['NAME']} where {T_U_R['FIELDS']['ROUND_ID']}=(select id from {T_ROUND['NAME']} \
    where {T_ROUND['FIELDS']['STARTS_AT']}={time}))''')
    data = cursor.fetchall()
    conn.close()
    return data


# @async1
def plan_all_round_jobs(job_queue):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()

    dt_now = datetime.now().timestamp()

    cursor.execute(
        f'''select distinct {T_ROUND['FIELDS']['GROUP_ID']} from {T_ROUND['NAME']} \
        WHERE {T_ROUND['FIELDS']['IS_FINISHED']}=False and {T_ROUND['FIELDS']['STARTS_AT']}>{dt_now}''')
    data = cursor.fetchall()
    conn.close()
    for group in data:
        # print(group[0])
        t = get_next_start_time(group[0])
        if t:
            dt = datetime.fromtimestamp(t)
            job_queue.run_once(round_start, dt, context=[group[0], job_queue], name=f'round_start {group[0]}')
            logger.info(f'Jobs for group {group[0]} added at {dt}')
            jobs = job_queue.jobs()
            for i in jobs:
                logger.warning(f'Job planned: {i.name}')

            drop_window_start = dt - timedelta(seconds=DROP_WINDOW)
            drop_announce_time = dt - timedelta(seconds=(DROP_WINDOW + DROP_ANNOUNCE))
            job_queue.run_once(drop_soon_announce, drop_announce_time, context=group[0], name=f'Drop announcement for group {group[0]}')
            job_queue.run_once(drop_window, drop_window_start, context=[group[0], job_queue],
                               name=f'Drop window for group {group[0]}')
            logger.info(f'Jobs for group {group[0]} added at {drop_window_start}')
            jobs = job_queue.jobs()
            for i in jobs:
                logger.warning(f'Job planned: {i.name}')

            add_to_times(group[0])
            logger.info(f'Queue: {job_queue.jobs()}')


def finish_past_rounds():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()

    dt_finish = (datetime.now() - timedelta(seconds=ROUND_TIME)).timestamp()
    cursor.execute(f'''update {T_ROUND['NAME']} set {T_ROUND['FIELDS']['IS_FINISHED']}=True, \
    {T_ROUND['FIELDS']['IN_PROGRESS']}=False where {T_ROUND['FIELDS']['STARTS_AT']}<{dt_finish}''')
    conn.commit()
    conn.close()
    logger.info('Past rounds finished')


@async1
def help(bot, update):
    bot.sendMessage(update.message.chat_id, texts.HELP + CHAT_GROUP)
    logger.info('Help message sent')

@async1
def get_next_round_time(bot, update):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()

    cursor.execute(f'''select {T_ROUND['FIELDS']['STARTS_AT']} from {T_ROUND['NAME']} \
    where {T_ROUND['FIELDS']['IN_PROGRESS']}=True \
    and {T_ROUND['FIELDS']['GROUP_ID']}={update.message.chat_id}''')
    data = cursor.fetchone()
    if data:
        t = datetime.fromtimestamp(data[0]) + timedelta(seconds=(ROUND_TIME + ROUNDS_INTERVAL -  DROP_WINDOW)) - datetime.now()
    else:
        dt_now = datetime.now().timestamp() # + timedelta(seconds=ROUND_TIME)).timestamp()
        cursor.execute(f'''select {T_ROUND['FIELDS']['STARTS_AT']} from {T_ROUND['NAME']} \
        where {T_ROUND['FIELDS']['STARTS_AT']} > {dt_now} \
        and {T_ROUND['FIELDS']['GROUP_ID']}={update.message.chat_id} order by id asc limit 1''')
        data = cursor.fetchone()
        if data:
            #t = datetime.fromtimestamp(data[0]).strftime('%H:%M:%S %Y-%m-%d ')
            t = datetime.fromtimestamp(data[0]) - timedelta(seconds=DROP_WINDOW) - datetime.now()
        else:
            t = 'NEVER'
    conn.close()
    message = texts.NEXT_ROUND + str(t).split(".")[0]
    bot.sendMessage(update.message.chat_id, message)
    logger.info(f'Round time sent: {t}')

def delete_check_message(bot, job):
    try:
        if is_admin(bot, job.context[2], job.context[0]):
            logger.warning(f'cannot delete check message from admin in {job.context[0]}')
        else:
            bot.delete_message(chat_id=job.context[0], message_id=job.context[1])
            logger.info(f'check message deleted in {job.context[0]}')
    except Exception as e:
        logger.exception(e)

def delete_bot_message(bot, job):
    try:
        bot.delete_message(chat_id=job.context[0], message_id=job.context[1])
        logger.info(f'check response deleted in {job.context[0]}')
    except Exception as e:
        logger.exception(e)

def get_links_to_check(api, insta_handle, participating_insta_links):
    handles = usernames_from_links(participating_insta_links)

    logger.info(f'{insta_handle} started manual check')
    list = []
    likers_missing = []
    comment_missing = []
    for user in handles:
        if user == insta_handle:
            continue
        else:
            try:
                logger.warning(f'{user} insta-check started')
                api.searchUsername(user)
                id = str(api.LastJson.get('user', "").get("pk", ""))
                api.getUserFeed(id)
                post_id = str(api.LastJson.get('items', "")[0].get("pk", ""))
                api.getMediaLikers(post_id)
                likers_handles = []
                for i in api.LastJson['users']:
                    likers_handles.append(str(i.get('username', "")))
                if not insta_handle in likers_handles:
                    likers_missing.append(user)
                user_comments = getComments(api, post_id)
                if not insta_handle in user_comments:
                    comment_missing.append(user)
                list.append(x for x in likers_missing)
                list.append(x for x in comment_missing)
                sleep(1.75)
            except Exception as e:
                logger.exception(e)
    logger.info(f'{insta_handle} LIKES MISSING: {likers_missing}')
    logger.info(f'{insta_handle} COMMENTS MISSING: {comment_missing}')
    return list



@async1
def check_engagement(bot, update, job_queue):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()

    cursor.execute(f'''SELECT * FROM {T_ROUND['NAME']} \
    WHERE {T_ROUND['FIELDS']['GROUP_ID']}={update.message.chat_id} \
    AND {T_ROUND['FIELDS']['IN_PROGRESS']}=True ORDER BY id ASC LIMIT 1''')
    data = cursor.fetchone()

    if data:

        cursor.execute(f'''SELECT {T_USER['FIELDS']['INSTA_LINK']} FROM {T_USER['NAME']} \
        WHERE {T_USER['FIELDS']['USER_ID']}={update.message.from_user.id}''')
        data = cursor.fetchone()[0]

        if data:

            insta_handle = handle_from_link(str(data))

            logger.info(f'Received /check command from {update.message.from_user.id}')
            cursor.execute(f'''SELECT {T_USER['FIELDS']['TG_NAME']} FROM {T_USER['NAME']} \
            WHERE {T_USER['FIELDS']['USER_ID']}={update.message.from_user.id}''')
            data = cursor.fetchone()[0]
            if data:
                name = '@' + str(data)
            else:
                cursor.execute(f'''SELECT {T_USER['FIELDS']['FULL_NAME']} FROM {T_USER['NAME']} \
                WHERE {T_USER['FIELDS']['USER_ID']}={update.message.from_user.id}''')
                name = str(cursor.fetchone()[0])

            cursor.execute(f'''SELECT {T_USER['FIELDS']['INSTA_LINK']} FROM {T_USER['NAME']} \
            WHERE id IN (SELECT {T_U_R['FIELDS']['USER_ID']} FROM {T_U_R['NAME']} \
            WHERE {T_U_R['FIELDS']['ROUND_ID']} IN (SELECT id FROM {T_ROUND['NAME']} \
            WHERE {T_ROUND['FIELDS']['GROUP_ID']}={update.message.chat_id} \
            AND {T_ROUND['FIELDS']['IN_PROGRESS']}=True))''')
            data = cursor.fetchall()
            participating_insta_links = []

            for i in data:
                for j in i:
                    participating_insta_links.append(j)
            logger.warning(f'PARTICIPATING INSTA LINKS ARE: {participating_insta_links}')

            check_result = get_links_to_check(api, insta_handle, participating_insta_links)

            if len(check_result) > 1:
                list_to_check = '\nwww.instagram.com/' + '\nwww.instagram.com/'.join(check_result)
            else:
                list_to_check = '\nwww.instagram.com/' + check_result[0]

            check_message = name + '\ncheck these users:\n' + list_to_check

            check_response = bot.sendMessage(update.message.chat_id, check_message, reply_to_message_id=update.message.message_id, disable_web_page_preview=True)
            logger_check_list = ' '.join(check_result)
            logger.info(f'{insta_handle} engagements missing: {logger_check_list}')

            time_of_deletion = datetime.now() + timedelta(seconds=60)
            job_queue.run_once(delete_check_message, time_of_deletion, context=[update.message.chat_id, update.message.message_id, update.message.from_user.id], name='delete check message from user')
            job_queue.run_once(delete_bot_message, time_of_deletion, context=[check_response.chat_id, check_response.message_id], name='delete check response from bot')
        else:
            bot.delete_message(chat_id=update.message.chat_id, message_id=update.message.message_id)
            logger.info('deleted /check message from non-participating user')
            check_not_parti = bot.sendMessage(update.message.chat_id, 'The /check command is only available for participants of the drop')
    else:
        bot.sendMessage(update.message.chat_id, 'The /check command only works when a round is in progress.')
    conn.close()

# def delete_next_round(update, job_queue):
#     conn = psycopg2.connect(DATABASE_URL, sslmode='require')
#     cursor = conn.cursor()
#     dt_now = datetime.now().timestamp()
#
#     cursor.execute(f'''DELETE FROM {T_ROUND} WHERE {T_ROUND['FIELDS']['GROUP_ID']}={update.message.chat_id} \
#     AND {T_ROUND['FIELDS']['STARTS_AT']}>{dt_now}''')
#     conn.commit()
#
#     logger.info(f'future rounds deleted: {update.message.chat_id}')
#     conn.close()
#
#
# def stop_future_rounds(bot, update, job_queue):
#     conn = psycopg2.connect(DATABASE_URL, sslmode='require')
#     cursor = conn.cursor()
#     dt_now = datetime.now().timestamp()
#     logger.info(f'received /stop command: {update.message.chat_id}')
#     if is_admin(bot, update.message.from_user.id,update.message.chat_id):
#         cursor.execute(f'''SELECT {T_ROUND['FIELDS']['STARTS_AT']} FROM {T_ROUND['NAME']} \
#         WHERE {T_ROUND['FIELDS']['GROUP_ID']}={update.message.chat_id} AND {T_ROUND['FIELDS']['STARTS_AT']}>{dt_now}''')
#         data = cursor.fetchone()
#         if data:
#             delete_next_round(update, job_queue)
#         else:
#             job_queue.run_once(delete_next_round, (dt_now + timedelta(seconds=ROUND_TIME)), context=[update.message.chat_id, job_queue], name='planned deletion of next round')
#     else:
#         bot.sendMessage(update.message.chat_id, texts.PERMISSION_ERROR)
#     conn.close()

def setup():
    logging.basicConfig(level=logging.WARNING)
    updater = Updater(TOKEN, request_kwargs={'read_timeout': 15, 'connect_timeout': 15})
    # updater = Updater(TOKEN, request_kwargs={'read_timeout': 12, 'connect_timeout': 12,
    #                                          'proxy_url': 'socks5://u0k12.tgproxy.me:1080/',
    #                                          'urllib3_proxy_kwargs': {'username': 'telegram', 'password': 'telegram'}})
    j = updater.job_queue
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("setup", new_group_setup, pass_args=True, pass_job_queue=True))
    # dp.add_handler(CommandHandler("stop", stop_future_rounds, pass_job_queue=True))
    dp.add_handler(CommandHandler("help", help))
    dp.add_handler(CommandHandler("nextround", get_next_round_time))
    dp.add_handler(CommandHandler("check", check_engagement, pass_job_queue=True))
    dp.add_handler(MessageHandler(Filters.text, echo))
    #dp.add_handler(MessageHandler(Filters.status_update.new_chat_members, new_user_welcome))
    dp.add_error_handler(error)
    updater.start_polling()

    finish_past_rounds()
    logger.info('Past rounds finished')

    plan_all_round_jobs(j)
    logger.info(f'Jobs planned: {j.jobs()}')
    logger.info('Bot: started')
    updater.idle()


if __name__ == '__main__':
    api = InstagramAPI(INSTA_USERNAME, INSTA_PASSWORD)
    sleep(1)
    api.login()
    sleep(1)
    logger.info('Instagram account(s): ready')

    # TODO если надо будет обновлять конфиг в лайве
    # wm = pyinotify.WatchManager()
    # s1 = pyinotify.Stats()  # Stats is a subclass of ProcessEvent
    # notifier1 = pyinotify.ThreadedNotifier(wm, default_proc_fun=Identity(s1))
    # notifier1.start()
    # wm.add_watch(FOLDER_PATH, pyinotify.IN_MODIFY, rec=True, auto_add=True)
    # logger.info('Watchdog: ready')
    setup()
