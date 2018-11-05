# -*- coding: utf-8 -*-
import logging
import re
import sqlite3

from datetime import datetime, timedelta
from threading import Thread
from time import sleep
from emoji import emojize

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
insta_user_pattern = re.compile(r'^(http)?s?(\://)?(www\.)?[iI]nstagram\.com/[^/].*?/?$')

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
                                  update.message.from_user.id)
            else:
                add_to_next_round(update.message.from_user.id, update.message.chat.id, text,
                                  update.message.from_user.id)
            bot.sendMessage(update.message.chat_id, texts.LINK_ADDED)

        else:
            bot.delete_message(chat_id=update.message.chat.id, message_id=update.message.message_id)
            logger.info('Wrong time. Message has been deleted: {}'.format(text))


def usernames_from_links(arr):
    res = []
    for i in arr:
        if not i:
            continue
        if i[-1] == '/':
            i = i[:-1]
        username = i.rsplit('/', maxsplit=1)[-1]
        res.append(username)
    return res


# @async1
def add_to_next_round(tg_name, chatid, insta_link, userid):
    conn = sqlite3.connect(DB_NAME)
    conn.set_trace_callback(print)
    cursor = conn.cursor()
    cursor.execute(f'''SELECT * from {T_USER['NAME']} where {T_USER['FIELDS']['TG_NAME']}=?''', (tg_name,))
    data = cursor.fetchall()
    if not data:  # если пользователя нет в таблице users, добавляем
        query = f'''INSERT INTO {T_USER['NAME']} ({T_USER['FIELDS']['TG_NAME']}, {T_USER['FIELDS']['INSTA_LINK']}, \
        {T_USER['FIELDS']['USER_ID']}) VALUES (?, ?, ?)'''
        cursor.execute(query, (tg_name, insta_link, userid))
        conn.commit()
        logger.info(f'{insta_link} inserted')
    else:  # если есть - обновляем ссылку на инсту
        query = f'''UPDATE {T_USER['NAME']} SET {T_USER['FIELDS']['INSTA_LINK']}=? \
                                            WHERE {T_USER['FIELDS']['TG_NAME']}=?'''
        cursor.execute(query, (insta_link, tg_name))
        conn.commit()
        logger.info(f'{insta_link} changed')

    query = f'''SELECT * from {T_U_R['NAME']} WHERE {T_U_R['FIELDS']['USER_ID']}\
    =(SELECT id from {T_USER['NAME']} where {T_USER['FIELDS']['TG_NAME']}=? LIMIT 1)\
    AND {T_U_R['FIELDS']['ROUND_ID']}\
    =(SELECT id from {T_ROUND['NAME']} WHERE {T_ROUND['FIELDS']['GROUP_ID']}=? \
    AND {T_ROUND['FIELDS']['IS_FINISHED']}=0 ORDER BY id ASC LIMIT 1)'''
    cursor.execute(query, (tg_name, chatid))
    data = cursor.fetchall()
    if not data:  # если пользователь не связан с раундом
        query = f'''INSERT INTO {T_U_R['NAME']} VALUES ((select id from {T_USER['NAME']} \
        where {T_USER['FIELDS']['TG_NAME']}=? order by id asc limit 1), \
        (SELECT id from {T_ROUND['NAME']} WHERE {T_ROUND['FIELDS']['GROUP_ID']}=? \
        AND {T_ROUND['FIELDS']['IS_FINISHED']}=0 ORDER BY id ASC LIMIT 1))'''
        cursor.execute(query, (tg_name, chatid))  # creates new round_start
        conn.commit()
        logger.info('Record added')


def get_next_start_time(chatid):
    dt_now = datetime.now().timestamp()

    conn = sqlite3.connect(DB_NAME)
    conn.set_trace_callback(print)
    cursor = conn.cursor()
    query = f'''SELECT {T_ROUND['FIELDS']['STARTS_AT']} from {T_ROUND['NAME']} WHERE {T_ROUND['FIELDS']['GROUP_ID']}=? \
    AND {T_ROUND['FIELDS']['IS_FINISHED']}=0 and {T_ROUND['FIELDS']['STARTS_AT']}>{dt_now} ORDER BY id ASC LIMIT 1'''
    cursor.execute(query, (chatid,))
    data = cursor.fetchall()
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


def new_user_welcome(bot, update):
    for i in update.message.new_chat_members:
        bot.restrict_chat_member(chat_id=update.message.chat.id, user_id=i.id, can_send_messages=True,
                                 can_add_web_page_previews=False)
        logger.info('User {} has been restricted from send web page previews'.format(i.id))
        bot.sendMessage(update.message.chat.id, 'Hi @' + str(i.username) + emojize(texts.WELCOME), disable_web_page_preview=True)
        logger.info('Welcome message sent')


def is_admin(bot, userid, chatid):
    admins = [admin.user.id for admin in bot.get_chat_administrators(chatid)]
    return userid in admins


# @async1
def new_group_setup(bot, update, args, job_queue):
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

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        conn.set_trace_callback(print)
        dt_now = datetime.now().timestamp()
        cursor.execute(f'''select * from {T_ROUND['NAME']} where {T_ROUND['FIELDS']['STARTS_AT']}>{dt_now} \
        and {T_ROUND['FIELDS']['GROUP_ID']}={update.message.chat_id}''')
        data = cursor.fetchall()  # если для этой группы уже есть раунд в будущем, то новый не добавится
        if not data:
            query = f'''INSERT INTO {T_ROUND['NAME']} ({T_ROUND['FIELDS']['STARTS_AT']}, \
            {T_ROUND['FIELDS']['GROUP_ID']}) VALUES (?, ?)'''
            cursor.execute(query, (next_round_starts, update.message.chat_id))  # creates new round_start
            conn.commit()
            bot.sendMessage(update.message.chat.id, texts.SETUP_SUCCESS)
            logger.info(f'New round set to {args}')

            plan_all_round_jobs(job_queue)
        else:
            bot.sendMessage(update.message.chat.id, texts.ROUND_ALREADY_SET)
            logger.info("There's a round for this group in the future")


def drop_window(bot, job):
    logger.warning('Drop window started')
    bot.sendMessage(job.context, texts.GIMME_UR_LINKS, disable_web_page_preview=True)
    logger.info(f'Drop window started: {job.context}')


def check_instagram(api, lst):
    logger.info('Checking Instagram...')
    result = gather(api, lst)
    approved = check(result, lst)
    res = list(set(lst) - set(approved))
    return res


@async1
def check45(bot, job):
    logger.warning('45 mins check')
    chatid = job.context[0]
    nicks = job.context[1]

    pidorases = check_instagram(api, nicks)
    if not pidorases:
        logging.info('All users had liked&commented each other')
    else:
        logging.info(f"These users did not complete the requirements: {pidorases}")
        lst = ['@' + x for x in get_bad_users(pidorases)]
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
        bot.sendMessage(chatid, texts.ROUND_SUCCESS)
    else:
        lst = ['@' + x for x in get_bad_users(pidorases)]
        list_to_send = '\n'.join(lst)
        bot.sendMessage(chatid, texts.BAD_USERS + list_to_send)

    goods = list(set(nicks) - set(pidorases))
    check_for_pidority(goods, pidorases, chatid, bot)
    mark_as_pidorases(pidorases)
    bot.sendMessage(chatid, texts.ROUND_FINISHED)
    bot.sendMessage(chatid, f'Next round starts in {timedelta(seconds=ROUNDS_INTERVAL)}')

    end_and_plan_next([chatid, job_queue])


def check_for_pidority(g, p, chatid, bot):
    conn = sqlite3.connect(DB_NAME)
    conn.set_trace_callback(print)
    cursor = conn.cursor()
    for i in p:
        cursor.execute(f'''select {T_USER['FIELDS']['USER_ID']} from {T_USER['NAME']} \
        where {T_USER['FIELDS']['IS_P']}=1 and {T_USER['FIELDS']['INSTA_LINK']} like ?''', (f'%{i}%',))
        data = cursor.fetchone()
        if data:
            print(f'check_for_pidority', data[0])
            ban(bot, data[0], chatid)

    increment_good_counter(g)


def mark_as_pidorases(lst):
    conn = sqlite3.connect(DB_NAME)
    conn.set_trace_callback(print)
    cursor = conn.cursor()
    for i in lst:
        cursor.execute(f'''update {T_USER['NAME']} set {T_USER['FIELDS']['IS_P']}=1
         where {T_USER['FIELDS']['INSTA_LINK']} like ?''', (f'%{i}%',))
        logger.warning(f'{i} marked as a bad one')
    conn.commit()


@async1
def ban(bot, userid, chatid):
    conn = sqlite3.connect(DB_NAME)
    conn.set_trace_callback(print)
    cursor = conn.cursor()

    cursor.execute (f'''select {T_USER['FIELDS']['TG_NAME']} from {T_USER['NAME']} \
    where {T_USER['FIELDS']['USER_ID']} = ?''', (userid,)) # need to figure out which var to pass here
    tg_name = cursor.fetchone()

    bot.restrict_chat_member(chatid, userid, until_date = (datetime.now() + timedelta(seconds=BAD_USER_BAN_TIME)).timestamp(), can_send_messages = False)
    logger.warning(f'{userid} id has been restricted from posting for 15 days')
    bot.sendMessage(chatid, '@' + ''.join(tg_name) + texts.BANNED)

def increment_good_counter(whom):
    conn = sqlite3.connect(DB_NAME)
    conn.set_trace_callback(print)
    cursor = conn.cursor()

    for i in whom:
        cursor.execute(f'''update {T_USER['NAME']} set {T_USER['FIELDS']['BAN_WARNS']}={T_USER['FIELDS']['BAN_WARNS']}+1 \
        where {T_USER['FIELDS']['INSTA_LINK']} like ?''', (f'%{i}%',))
    conn.commit()

    cursor.execute(
        f'''update {T_USER['NAME']} set {T_USER['FIELDS']['IS_P']}=0  where {T_USER['FIELDS']['BAN_WARNS']}>=10''')
    conn.commit()

    cursor.execute(
        f'''update {T_USER['NAME']} set {T_USER['FIELDS']['BAN_WARNS']}=0  where {T_USER['FIELDS']['IS_P']}=0''')
    conn.commit()


def get_bad_users(usrs):
    res = list()
    conn = sqlite3.connect(DB_NAME)
    conn.set_trace_callback(print)
    cursor = conn.cursor()
    for i in usrs:
        cursor.execute(f'''select distinct {T_USER['FIELDS']['TG_NAME']} from {T_USER['NAME']} \
        WHERE {T_USER['FIELDS']['INSTA_LINK']} like ?''', (f'%{i}%',))
        data = cursor.fetchone()
        if data:
            res.append(data[0])
    return res


def end_and_plan_next(cont):
    chatid = cont[0]
    job_queue = cont[1]
    conn = sqlite3.connect(DB_NAME)
    conn.set_trace_callback(print)
    cursor = conn.cursor()


    cursor.execute(f'''update {T_ROUND['NAME']} set {T_ROUND['FIELDS']['IS_FINISHED']}=1 where \
    {T_ROUND['FIELDS']['IS_FINISHED']}=0 and {T_ROUND['FIELDS']['STARTS_AT']}={times[chatid]}''')
    conn.commit()
    logger.info('Round has ended')

    next_start_time = (datetime.now() + timedelta(seconds=ROUNDS_INTERVAL)).timestamp()

    query = f'''INSERT INTO {T_ROUND['NAME']} ({T_ROUND['FIELDS']['STARTS_AT']}, \
    {T_ROUND['FIELDS']['GROUP_ID']}) VALUES (?, ?)'''
    cursor.execute(query, (next_start_time, chatid))  # creates new round_start
    conn.commit()

    logger.info(f'New round set to {datetime.fromtimestamp(next_start_time)}')
    plan_all_round_jobs(job_queue)


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
        end_and_plan_next(job.context)
    elif len(links) == 1:
        logger.warning('Not enough users for the round')
        bot.sendMessage(job.context[0], texts.USER_SO_ALONE)
        end_and_plan_next(job.context)

    else:  # plan 45min alert
        nicknames = usernames_from_links(links)
        logger.info(f'nicknames: {nicknames}, links: {links}')
        bot.sendMessage(job.context[0], texts.ROUND_STARTED)
        links_list = '\n'.join(links)
        logger.info(f'Links for this round ({job.context[0]}): {links_list}')
        bot.sendMessage(job.context[0], links_list, disable_web_page_preview=True)
        job.context[1].run_once(check45, (ROUND_TIME // 4) * 3, context=[job.context[0], nicknames],
                                name=f'45min alert for {job.context[0]}')
        job.context[1].run_once(final_check, ROUND_TIME, context=[job.context[0], nicknames, job.context[1]],
                                name=f'final checking for {job.context[0]}')
        logger.info(f'Checkings planned: {job.context[1].jobs()}')


def get_round_links(time):
    conn = sqlite3.connect(DB_NAME)
    conn.set_trace_callback(print)
    cursor = conn.cursor()
    cursor.execute(f'''select {T_USER['FIELDS']['INSTA_LINK']} from {T_USER['NAME']} \
    where id in (select id from {T_U_R['NAME']} where {T_U_R['FIELDS']['ROUND_ID']}=(select id from {T_ROUND['NAME']} \
    where {T_ROUND['FIELDS']['STARTS_AT']}={time}))''')
    data = cursor.fetchall()
    return data


# @async1
def plan_all_round_jobs(job_queue):
    conn = sqlite3.connect(DB_NAME)
    conn.set_trace_callback(print)
    cursor = conn.cursor()

    dt_now = datetime.now().timestamp()

    cursor.execute(
        f'''select distinct {T_ROUND['FIELDS']['GROUP_ID']} from {T_ROUND['NAME']} \
        WHERE {T_ROUND['FIELDS']['IS_FINISHED']}=0 and {T_ROUND['FIELDS']['STARTS_AT']}>{dt_now}''')
    data = cursor.fetchall()
    for group in data:
        # print(group[0])
        t = get_next_start_time(group[0])
        if t:
            dt = datetime.fromtimestamp(t)
            job_queue.run_once(round_start, dt, context=[group[0], job_queue], name=f'Group {group[0]}')
            logger.info(f'Jobs for group {group[0]} added at {dt}')

            drop_window_start = dt - timedelta(seconds=DROP_WINDOW)
            job_queue.run_once(drop_window, drop_window_start, context=group[0],
                               name=f'Drop window for group {group[0]}')
            logger.info(f'Jobs for group {group[0]} added at {drop_window_start}')

            add_to_times(group[0])
            logger.info(f'Queue: {job_queue.jobs()}')


def finish_past_rounds():
    conn = sqlite3.connect(DB_NAME)
    conn.set_trace_callback(print)
    cursor = conn.cursor()

    dt_finish = (datetime.now() - timedelta(seconds=ROUND_TIME)).timestamp()
    cursor.execute(f'''update {T_ROUND['NAME']} set {T_ROUND['FIELDS']['IS_FINISHED']}=1 where \
    {T_ROUND['FIELDS']['IS_FINISHED']}=0 and {T_ROUND['FIELDS']['STARTS_AT']}<{dt_finish}''')
    conn.commit()
    logger.info('Past rounds finished')


@async1
def help(bot, update):
    bot.sendMessage(update.message.chat_id, texts.HELP)
    logger.info('Help message sent')

@async1
def get_next_round_time(bot, update):
    conn = sqlite3.connect(DB_NAME)
    conn.set_trace_callback(print)
    cursor = conn.cursor()

    dt_now = datetime.now().timestamp() # + timedelta(seconds=ROUND_TIME)).timestamp()
    cursor.execute(f'''select {T_ROUND['FIELDS']['STARTS_AT']} from {T_ROUND['NAME']} \
    where {T_ROUND['FIELDS']['STARTS_AT']} > {dt_now} \
    and {T_ROUND['FIELDS']['GROUP_ID']}={update.message.chat_id} order by id asc limit 1''')
    data = cursor.fetchone()
    if data:
        #t = datetime.fromtimestamp(data[0]).strftime('%H:%M:%S %Y-%m-%d ')
        t = datetime.fromtimestamp(data[0]) - datetime.now()
    else:
        t = 'NEVER'
    message = texts.NEXT_ROUND + str(t).split(".")[0]
    bot.sendMessage(update.message.chat_id, message)
    logger.info(f'Round time sent: {t}')


def setup():
    logging.basicConfig(level=logging.WARNING)
    updater = Updater(TOKEN)
    # updater = Updater(TOKEN, request_kwargs={'read_timeout': 12, 'connect_timeout': 12,
    #                                          'proxy_url': 'socks5://u0k12.tgproxy.me:1080/',
    #                                          'urllib3_proxy_kwargs': {'username': 'telegram', 'password': 'telegram'}})
    j = updater.job_queue
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("setup", new_group_setup, pass_args=True, pass_job_queue=True))
    dp.add_handler(CommandHandler("help", help))
    dp.add_handler(CommandHandler("nextround", get_next_round_time))
    dp.add_handler(MessageHandler(Filters.text, echo))
    dp.add_handler(MessageHandler(Filters.status_update.new_chat_members, new_user_welcome))
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
