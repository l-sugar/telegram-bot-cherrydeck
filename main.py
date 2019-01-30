# -*- coding: utf-8 -*-
import logging
import re
import psycopg2
import psycopg2.extras
from tenacity import *

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

sleep_time = 3
insta_user_pattern = re.compile('^([hH]ttp)?s?(://)?([wW]ww.)?[iI]nstagram.com/[^/][^p/].*?/?$')

times = {}  # {group_tg_id: closest round_start start timestamp}

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
            logger.info(f'{update.message.chat_id}: {update.message.from_user.id}s (admin) message has been passed')
        else:
            bot.delete_message(chat_id=update.message.chat.id, message_id=update.message.message_id)
            logger.info(f'{update.message.chat_id}: Message has been deleted: {update.message.from_user.full_name} : {text}')
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

        logger.info(f'{update.message.chat_id}: start: {start}, now: {now}, end: {end}')
        if start < now < end:
            if update.message.from_user.username:
                tg_name = update.message.from_user.username
            else:
                tg_name = None
            #bot.sendMessage(update.message.chat_id, texts.LINK_ADDED)
            add_to_next_round(tg_name, update.message.chat.id, text,
                              update.message.from_user.id, update.message.from_user.full_name)

        else:
            bot.delete_message(chat_id=update.message.chat.id, message_id=update.message.message_id)
            logger.info(f'{update.message.chat_id}: Wrong time. Message has been deleted: {update.message.from_user.full_name} : {text}')


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
        res.append(username.lower())
    return res

def handle_from_link(link):
    match = re.search('nstagram.com/[^/?]+', link)
    username = match.group().rsplit('/', maxsplit=1)[-1]
    return username.lower()

# @async1
def add_to_next_round(tg_name, chat_id, insta_link, userid, fullname):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()
    cursor.execute(f'''SELECT * from {T_USER['NAME']} where {T_USER['FIELDS']['USER_ID']}=%s''', (userid,))
    data = cursor.fetchall()
    if not data:
        query = f'''INSERT INTO {T_USER['NAME']} ({T_USER['FIELDS']['TG_NAME']}, {T_USER['FIELDS']['INSTA_LINK']}, \
        {T_USER['FIELDS']['USER_ID']}, {T_USER['FIELDS']['FULL_NAME']}) VALUES (%s, %s, %s, %s)'''
        cursor.execute(query, (tg_name, insta_link, userid, fullname))
        conn.commit()
        logger.info(f'{chat_id}: {insta_link} inserted into round')
    else:
        query = f'''UPDATE {T_USER['NAME']} SET {T_USER['FIELDS']['INSTA_LINK']}=%s, {T_USER['FIELDS']['FULL_NAME']}=%s \
                                            WHERE {T_USER['FIELDS']['USER_ID']}=%s'''
        cursor.execute(query, (insta_link, fullname, userid))
        conn.commit()
        logger.info(f'{chat_id}: {insta_link} changed')

    query = f'''SELECT * from {T_U_R['NAME']} WHERE {T_U_R['FIELDS']['USER_ID']}\
    =(SELECT id from {T_USER['NAME']} where {T_USER['FIELDS']['FULL_NAME']}=%s LIMIT 1)\
    AND {T_U_R['FIELDS']['ROUND_ID']}\
    =(SELECT id from {T_ROUND['NAME']} WHERE {T_ROUND['FIELDS']['GROUP_ID']}=%s \
    AND {T_ROUND['FIELDS']['IS_FINISHED']}=False ORDER BY id DESC LIMIT 1)'''
    cursor.execute(query, (fullname, chat_id))
    data = cursor.fetchall()
    if not data:
        query = f'''INSERT INTO {T_U_R['NAME']} VALUES ((select id from {T_USER['NAME']} \
        where {T_USER['FIELDS']['USER_ID']}=%s ORDER BY id asc limit 1), \
        (SELECT id from {T_ROUND['NAME']} WHERE {T_ROUND['FIELDS']['GROUP_ID']}=%s \
        AND {T_ROUND['FIELDS']['IS_FINISHED']}=False ORDER BY id ASC LIMIT 1))'''
        cursor.execute(query, (userid, chat_id))  # creates new round_start
        conn.commit()
        logger.info(f'{chat_id}: Record added')
    conn.close()


def get_next_start_time(chat_id):
    dt_now = datetime.now().timestamp()

    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()
    query = f'''SELECT {T_ROUND['FIELDS']['STARTS_AT']} from {T_ROUND['NAME']} WHERE {T_ROUND['FIELDS']['GROUP_ID']}=%s \
    AND {T_ROUND['FIELDS']['IS_FINISHED']}=False and {T_ROUND['FIELDS']['STARTS_AT']}>{dt_now} ORDER BY id ASC LIMIT 1'''
    cursor.execute(query, (chat_id,))
    data = cursor.fetchall()
    conn.close()
    if data:
        return data[0][0]
    return None


@async1
def add_to_times(chat_id):
    global times
    data = get_next_start_time(chat_id)
    logger.info(f'Adding to times: {chat_id}')
    # print(data)
    if data:
        # print(data)
        times[chat_id] = data
        logger.warning(f'Times: {times}')
        return data
    return None

@retry(stop=stop_after_attempt(5), wait=(wait_fixed(5) + wait_random(0, 1.5)))
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
                except Exception as e:
                    logger.warning('error while getting username from comment')
                    logger.exception(e)
                    raise
            sleep(sleep_time)
            next_max_id = api.LastJson.get('next_max_id', '')
        except Exception as e:
            logger.warning('error while getting comments')
            logger.exception(e)
            raise
    return comments


@retry(stop=stop_after_attempt(5), wait=(wait_fixed(5) + wait_random(0, 1.5)))
def gather(api, userList): # userList == [name1, name2, name3, ...]
    engagements = []
    # engagements = [engagements[tmp[likers][user_comments]]]
    # access spec liker: global_mas[0][0][0]
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
                engagements.append(tmp)
                sleep(1.75)
            except Exception as e:
                logger.exception(e)
                raise

        return engagements

    except Exception as e:
        logger.exception(e)
        raise


def check(res, users): # users == [name1, name2, name3, ...]
    approved = []
    missing_engagements = {}
    try:
        for _, i in enumerate(users):
            likes_missing = []
            comments_missing = []
            tmp = []
            if all(i in res[x][0] for x in range(len(res)) if x != _) and all(
                    i in res[x][1] for x in range(len(res)) if x != _):
                approved.append(i)
            else:
                for it, j in enumerate(res):
                    if (it == _):
                        continue
                    if (i not in res[it][0]):
                        likes_missing.append(users[it])
                    if (i not in res[it][1]):
                        comments_missing.append(users[it])
                tmp.append(likes_missing)
                tmp.append(comments_missing)
                missing_engagements[i] = tmp
        return approved, missing_engagements

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


def is_admin(bot, userid, chat_id):
    admins = [admin.user.id for admin in bot.get_chat_administrators(chat_id)]
    return userid in admins


# @async1
def new_group_setup(bot, update, args, job_queue):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()

    cursor.execute(f'''select * from {T_ROUND['NAME']} \
                    WHERE {T_ROUND['FIELDS']['IN_PROGRESS']}=True and {T_ROUND['FIELDS']['GROUP_ID']} = {update.message.chat.id}''')
    data = cursor.fetchall()
    conn.close()

    chat_id = update.message.chat.id
    if data:
        bot.sendMessage(chat_id, texts.ROUND_ALREADY_SET)
        logger.info(f'{chat_id}: There is a round for this group in progress right now')
        return
    else:
        logger.warning('/setup ' + str(args))
        if not args:
            bot.sendMessage(chat_id, texts.SETUP_MISSING_TIME)
            return

        if not is_admin(bot, update.message.from_user.id, chat_id):
            bot.sendMessage(chat_id, texts.PERMISSION_ERROR)
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
            bot.sendMessage(chat_id, texts.BAD_TIME_FORMAT)
        else:
            next_round_starts = dt.timestamp()

            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            cursor = conn.cursor()

            dt_now = datetime.now().timestamp()
            cursor.execute(f'''select * from {T_ROUND['NAME']} where {T_ROUND['FIELDS']['STARTS_AT']}>{dt_now} \
            and {T_ROUND['FIELDS']['GROUP_ID']}={chat_id}''')
            data = cursor.fetchall()
            if not data:
                query = f'''INSERT INTO {T_ROUND['NAME']} ({T_ROUND['FIELDS']['STARTS_AT']}, \
                {T_ROUND['FIELDS']['GROUP_ID']}) VALUES (%s, %s)'''
                cursor.execute(query, (next_round_starts, chat_id))  # creates new round_start
                conn.commit()
                #bot.sendMessage(update.message.chat.id, texts.SETUP_SUCCESS)
                logger.info(f'{chat_id}: New round set to {args}')

                plan_all_round_jobs(job_queue)
                jobs = job_queue.jobs()
                for i in jobs:
                    logger.warning(f'Job planned: {i.name} for group {chat_id}')
            else:
                bot.sendMessage(update.message.chat.id, texts.ROUND_ALREADY_SET)
                logger.info(f'{chat_id}: There is a round for this group in the future')
            conn.close()

def drop_window(bot, job):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()

    dt_now = datetime.now().timestamp()
    chat_id = job.context[0]
    job_queue = job.context[1]

    cursor.execute(f'''update {T_ROUND['NAME']} SET {T_ROUND['FIELDS']['IN_PROGRESS']}=True \
    WHERE {T_ROUND['FIELDS']['STARTS_AT']} > {dt_now} \
    AND {T_ROUND['FIELDS']['GROUP_ID']} = {chat_id}''')
    conn.commit()
    conn.close()

    logger.warning('Drop window started')
    bot.sendMessage(chat_id, texts.GIMME_UR_LINKS, disable_web_page_preview=True)
    logger.info(f'Drop window started: {chat_id}')

    job_queue.run_once(drop_alert, (DROP_ENDS_SOON), context=chat_id, name='plan drop_alert')
    jobs = job_queue.jobs()
    for i in jobs:
        logger.warning(f'Job planned: {i.name} for group {chat_id}')


@async1
def drop_alert(bot, job):
    chat_id = job.context
    bot.sendMessage(chat_id, texts.DROP_ALMOST_OVER)
    logger.warning(f'drop_alert sent for group {chat_id}')

def drop_soon_announce(bot, job):
    chat_id = job.context
    bot.sendMessage(chat_id, texts.DROP_SOON)
    logger.warning(f'Drop announcement sent for group {chat_id}')

def check_instagram(lst):
    api = next(apis)
    logger.info('Checking Instagram...')
    result = gather(api, lst)
    approved, missing_engagements = check(result, lst)
    res = list(set(lst) - set(approved))
    logger.info(res)
    return res, missing_engagements


@async1
def check45(bot, job):
    chat_id = job.context[0]
    nicks = job.context[1]

    logger.warning(f'{chat_id}: 45 mins check')

    pidorases, missing_engagements = check_instagram(nicks)
    if not pidorases:
        logger.info(f'{chat_id} check45: All users had liked&commented each other')
    else:
        lst = [x for x in get_bad_users(pidorases)]
        list_to_send = '\n'.join(lst)
        logger.info(f'{chat_id}: These users did not complete the requirements: {lst}')
        bot.sendMessage(chat_id, texts.BAD_CONDITIONS + list_to_send)
        for insta_handle in missing_engagements:
            missing_likes = missing_engagements.get(insta_handle, "")[0]
            missing_comments = missing_engagements.get(insta_handle, "")[1]
            logger.warning(f'{chat_id} 45min check: {insta_handle}\nlikes missing: {missing_likes}\ncomments missing: {missing_comments}')


def final_check(bot, job):
    chat_id = job.context[0]
    nicks = job.context[1]
    job_queue = job.context[2]
    logger.warning(f'{chat_id}: Final check initiated')

    pidorases, missing_engagements = check_instagram(nicks)
    if not pidorases:
        logger.info(f'{chat_id}: All users have engaged with each other')
        #bot.sendMessage(chat_id, texts.ROUND_SUCCESS)
    else:
        lst = [x for x in get_bad_users(pidorases)]
        list_to_send = '\n'.join(lst)
        bot.sendMessage(chat_id, texts.BAD_USERS + list_to_send + texts.BAD_BEHAVIOR_INFO)
        for insta_handle in missing_engagements:
            missing_likes = missing_engagements.get(insta_handle, "")[0]
            missing_comments = missing_engagements.get(insta_handle, "")[1]
            logger.warning(f'{chat_id} final check: {insta_handle}\nlikes missing: {missing_likes}\ncomments missing: {missing_comments}')

    goods = list(set(nicks) - set(pidorases))
    check_if_bans_necessary(goods, pidorases, chat_id, bot)
    mark_as_pidorases(pidorases)

    end_and_plan_next(bot, [chat_id, job_queue])

def announce_round_finish(bot, chat_id):
    bot.sendMessage(chat_id, texts.ROUND_FINISHED)
    bot.sendMessage(chat_id, f'Next Drop starts in {timedelta(seconds=ROUNDS_INTERVAL) - timedelta(seconds=DROP_WINDOW)}')


def check_if_bans_necessary(g, p, chat_id, bot):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()
    for i in p:
        cursor.execute(f'''select {T_USER['FIELDS']['USER_ID']} from {T_USER['NAME']} \
        where {T_USER['FIELDS']['BAN_WARNS']}=2 and {T_USER['FIELDS']['INSTA_LINK']} like %s''', (f'%{i}%',))
        data = cursor.fetchone()
        if data:
            print(f'user has reached ban limit:', data[0])
            if is_admin(bot, data[0], chat_id):
                logger.warning(f'{chat_id}: Cannot restrict admin')
            else:
                ban(bot, data[0], chat_id)
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
def ban(bot, userid, chat_id):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()

    cursor.execute (f'''select {T_USER['FIELDS']['FULL_NAME']} from {T_USER['NAME']} \
    where {T_USER['FIELDS']['USER_ID']} = %s''', (userid,))
    user_name = cursor.fetchone()
    conn.close()

    bot.restrict_chat_member(chat_id, userid, until_date = (datetime.now() + timedelta(seconds=BAD_USER_BAN_TIME)).timestamp(), can_send_messages = False)
    logger.warning(f'{chat_id}: {userid} id has been restricted from posting for 15 days')
    bot.sendMessage(chat_id, ''.join(user_name) + texts.BANNED)

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
    chat_id = cont[0]
    job_queue = cont[1]
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()


    cursor.execute(f'''update {T_ROUND['NAME']} \
    set {T_ROUND['FIELDS']['IS_FINISHED']}=True, {T_ROUND['FIELDS']['IN_PROGRESS']}=False where \
    {T_ROUND['FIELDS']['IS_FINISHED']}=False and {T_ROUND['FIELDS']['STARTS_AT']}={times[chat_id]}''')
    conn.commit()
    logger.info(f'{chat_id}: Round has ended')
    jobs = job_queue.jobs()
    for i in jobs:
        logger.warning(f'Job planned: {i.name} in group {chat_id}')

    next_start_time = (datetime.now() + timedelta(seconds=ROUNDS_INTERVAL)).timestamp()

    cursor.execute(f'''UPDATE {T_USER['NAME']} set {T_USER['FIELDS']['INSTA_LINK']} = NULL \
    WHERE id in (select distinct {T_U_R['FIELDS']['USER_ID']} from {T_U_R['NAME']} \
    where {T_U_R['FIELDS']['ROUND_ID']} in (select distinct id from {T_ROUND['NAME']} \
    where {T_ROUND['FIELDS']['IS_FINISHED']}=True and {T_ROUND['FIELDS']['GROUP_ID']}={chat_id}))''')
    conn.commit()

    query = f'''INSERT INTO {T_ROUND['NAME']} ({T_ROUND['FIELDS']['STARTS_AT']}, \
    {T_ROUND['FIELDS']['GROUP_ID']}) VALUES (%s, %s)'''
    cursor.execute(query, (next_start_time, chat_id))  # creates new round_start
    conn.commit()
    conn.close()

    logger.info(f'{chat_id}: New round set to {datetime.fromtimestamp(next_start_time)}')
    plan_all_round_jobs(job_queue)
    announce_round_finish(bot, chat_id)


# @async1
def round_start(bot, job):
    chat_id = job.context[0]
    # job.context[1] = job_queue
    logger.warning(f'{chat_id}: Round started')
    t = times[chat_id]
    logger.warning(f'{chat_id}: Time: {t}')
    links = get_round_links(t, chat_id)

    if links:
        links = [x[0] for x in links]

    if not links:
        logger.warning(f'{chat_id}: No links for this round')
        bot.sendMessage(chat_id, texts.NO_USERS_PARTICIPATE)
        end_and_plan_next(bot, job.context)
    elif len(links) == 1:
        logger.warning(f'{chat_id}: Not enough users for the round')
        bot.sendMessage(chat_id, texts.USER_SO_ALONE)
        end_and_plan_next(bot, job.context)

    else:  # plan 45min alert
        nicknames = usernames_from_links(links)
        logger.info(f'{chat_id}: nicknames: {nicknames}, links: {links}')
        bot.sendMessage(chat_id, texts.ROUND_STARTED)
        links_list = '\n\n'.join(links)
        logger.info(f'{chat_id}: Links for this round: {links_list}')
        bot.sendMessage(chat_id, links_list, disable_web_page_preview=True)
        bot.sendMessage(chat_id, texts.ROUND_START_RULES)
        job.context[1].run_once(check45, (ROUND_TIME // 4) * 3, context=[chat_id, nicknames],
                                name=f'45min alert')
        job.context[1].run_once(final_check, ROUND_TIME, context=[chat_id, nicknames, job.context[1]],
                                name=f'final checking')
        logger.info(f'{chat_id}: Checkings planned: {job.context[1].jobs()}')
        jobs = job.context[1].jobs()
        for i in jobs:
            logger.warning(f'Job planned: {i.name} in group {chat_id}')


def get_round_links(time, chat_id):

    logger.warning(f'{chat_id}: starting collection of links from DB')
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()
    cursor.execute(f'''select {T_USER['FIELDS']['INSTA_LINK']} from {T_USER['NAME']} \
    where id in (select {T_U_R['FIELDS']['USER_ID']} from {T_U_R['NAME']} where {T_U_R['FIELDS']['ROUND_ID']}=(select id from {T_ROUND['NAME']} \
    where {T_ROUND['FIELDS']['STARTS_AT']}={time} AND \
    {T_ROUND['FIELDS']['GROUP_ID']}={chat_id}))''')
    data = cursor.fetchall()
    conn.close()
    if not data:
        logger.warning(f'{chat_id}: NO links found in DB for this group and round')
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
            global times
            if group[0] in times:
                if times[group[0]] == t:
                    continue

            dt = datetime.fromtimestamp(t)
            drop_window_start = dt - timedelta(seconds=DROP_WINDOW)
            drop_announce_time = dt - timedelta(seconds=(DROP_WINDOW + DROP_ANNOUNCE))

            job_queue.run_once(round_start, dt, context=[group[0], job_queue], name=f'round_start {group[0]}')
            job_queue.run_once(drop_soon_announce, drop_announce_time, context=group[0], name=f'Drop announcement for group {group[0]}')
            job_queue.run_once(drop_window, drop_window_start, context=[group[0], job_queue], name=f'Drop window for group {group[0]}')
            logger.info(f'Next drop & round for group {group[0]} added at {drop_window_start}')
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
    chat_id = update.message.chat_id
    bot.sendMessage(chat_id, texts.HELP + CHAT_GROUP)
    logger.info(f'{chat_id}: Help message sent')

@async1
def get_next_round_time(bot, update):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()

    chat_id = update.message.chat_id

    cursor.execute(f'''select {T_ROUND['FIELDS']['STARTS_AT']} from {T_ROUND['NAME']} \
    where {T_ROUND['FIELDS']['IN_PROGRESS']}=True \
    and {T_ROUND['FIELDS']['GROUP_ID']}={chat_id}''')
    data = cursor.fetchone()
    if data:
        t = datetime.fromtimestamp(data[0]) + timedelta(seconds=(ROUND_TIME + ROUNDS_INTERVAL -  DROP_WINDOW)) - datetime.now()
    else:
        dt_now = datetime.now().timestamp() # + timedelta(seconds=ROUND_TIME)).timestamp()
        cursor.execute(f'''select {T_ROUND['FIELDS']['STARTS_AT']} from {T_ROUND['NAME']} \
        where {T_ROUND['FIELDS']['STARTS_AT']} > {dt_now} \
        and {T_ROUND['FIELDS']['GROUP_ID']}={chat_id} order by id asc limit 1''')
        data = cursor.fetchone()
        if data:
            #t = datetime.fromtimestamp(data[0]).strftime('%H:%M:%S %Y-%m-%d ')
            t = datetime.fromtimestamp(data[0]) - timedelta(seconds=DROP_WINDOW) - datetime.now()
        else:
            t = 'NEVER'
    conn.close()
    message = texts.NEXT_ROUND + str(t).split(".")[0]
    bot.sendMessage(chat_id, message)
    logger.info(f'{chat_id}: Round time sent: {t}')

def delete_check_message(bot, job):
        bot.delete_message(chat_id=job.context[0], message_id=job.context[1])
        logger.info(f'check message deleted in {job.context[0]}')

# def get_links_to_check(api, insta_handle, participating_insta_links):
#     handles = usernames_from_links(participating_insta_links)
#
#     logger.info(f'{insta_handle} started manual check')
#     list = []
#     likers_missing = []
#     comment_missing = []
#
#     api.login()
#     for user in handles:
#         if user == insta_handle:
#             continue
#         else:
#             logger.warning(f'{insta_handle} : {user} insta-check started')
#             api.searchUsername(user)
#             id = str(api.LastJson.get('user', "").get("pk", ""))
#             api.getUserFeed(id)
#             post_id = str(api.LastJson.get('items', "")[0].get("pk", ""))
#             api.getMediaLikers(post_id)
#             likers_handles = []
#             for i in api.LastJson['users']:
#                 likers_handles.append(str(i.get('username', "")))
#             if not insta_handle in likers_handles:
#                 likers_missing.append(user)
#             else:
#                 user_comments = getComments(api, post_id)
#                 if not insta_handle in user_comments:
#                     comment_missing.append(user)
#             for i in likers_missing:
#                 list.append(str(i))
#             for j in comment_missing:
#                 list.append(str(j))
#             sleep(1.75)
#     logger.info(f'{insta_handle} LIKES MISSING: {likers_missing}')
#     logger.info(f'{insta_handle} COMMENTS MISSING: {comment_missing}')
#     return list



@async1
def check_engagement(bot, update, job_queue):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id

    cursor.execute(f'''SELECT * FROM {T_ROUND['NAME']} \
    WHERE {T_ROUND['FIELDS']['GROUP_ID']}={chat_id} \
    AND {T_ROUND['FIELDS']['IN_PROGRESS']}=True ORDER BY id ASC LIMIT 1''')
    data = cursor.fetchone()

    if data:

        cursor.execute(f'''SELECT * FROM {T_U_R['NAME']} WHERE {T_U_R['FIELDS']['ROUND_ID']} IN \
        (SELECT id FROM {T_ROUND['NAME']} WHERE {T_ROUND['FIELDS']['GROUP_ID']}={chat_id} AND \
        {T_ROUND['FIELDS']['IN_PROGRESS']}=True) AND \
        {T_U_R['FIELDS']['USER_ID']} IN (SELECT id FROM {T_USER['NAME']} WHERE \
        {T_USER['FIELDS']['USER_ID']}={user_id})''')
        data = cursor.fetchone()

        if data:

            cursor.execute(f'''SELECT {T_USER['FIELDS']['INSTA_LINK']} FROM {T_USER['NAME']} \
            WHERE {T_USER['FIELDS']['USER_ID']}={user_id}''')
            data = cursor.fetchone()

            if data:

                insta_handle = handle_from_link(str(data[0]))

                logger.info(f'{chat_id}: Received /check command from {insta_handle}')
                cursor.execute(f'''SELECT {T_USER['FIELDS']['TG_NAME']} FROM {T_USER['NAME']} \
                WHERE {T_USER['FIELDS']['USER_ID']}={user_id}''')
                data = cursor.fetchone()[0]
                if data:
                    name = '@' + str(data)
                else:
                    cursor.execute(f'''SELECT {T_USER['FIELDS']['FULL_NAME']} FROM {T_USER['NAME']} \
                    WHERE {T_USER['FIELDS']['USER_ID']}={user_id}''')
                    name = str(cursor.fetchone()[0])

                cursor.execute(f'''SELECT {T_USER['FIELDS']['INSTA_LINK']} FROM {T_USER['NAME']} \
                WHERE id IN (SELECT {T_U_R['FIELDS']['USER_ID']} FROM {T_U_R['NAME']} \
                WHERE {T_U_R['FIELDS']['ROUND_ID']} IN (SELECT id FROM {T_ROUND['NAME']} \
                WHERE {T_ROUND['FIELDS']['GROUP_ID']}={chat_id} \
                AND {T_ROUND['FIELDS']['IN_PROGRESS']}=True))''')
                data = cursor.fetchall()
                participating_insta_links = []

                for i in data:
                    for j in i:
                        participating_insta_links.append(str(j))
                logger.warning(f'{chat_id}: PARTICIPATING INSTA LINKS ARE: {participating_insta_links}')


                handles = usernames_from_links(participating_insta_links)

                logger.info(f'{chat_id}: manual check started by {insta_handle}')
                output_list = []
                likers_missing = []
                comment_missing = []

                @retry(stop=stop_after_attempt(5), wait=(wait_fixed(10) + wait_random(5, 10)))
                def get_pic_engagements(user):
                    api = next(apis)
                    try:
                        logger.warning(f'{chat_id}: {insta_handle} : {user} insta-check started')
                        api.searchUsername(user)
                        id = str(api.LastJson.get('user', "").get("pk", ""))
                        api.getUserFeed(id)
                        post_id = str(api.LastJson.get('items', "")[0].get("pk", ""))
                        api.getMediaLikers(post_id)
                        likers_handles = []
                        for i in api.LastJson['users']:
                            likers_handles.append(str(i.get('username', "")))
                        if insta_handle not in likers_handles:
                            likers_missing.append(user)
                        else:
                            user_comments = getComments(api, post_id)
                            if insta_handle not in user_comments:
                                comment_missing.append(user)
                        for i in likers_missing:
                            if i not in output_list:
                                output_list.append(str(i))
                        for j in comment_missing:
                            if j not in output_list:
                                output_list.append(str(j))
                        sleep(1)
                    except Exception as e:
                        logger.exception(e)
                        raise



                for user in handles:
                    if user == insta_handle:
                        continue
                    else:
                        get_pic_engagements(user)


                logger.info(f'{chat_id}: {insta_handle} LIKES MISSING: {likers_missing}')
                logger.info(f'{chat_id}: {insta_handle} COMMENTS MISSING: {comment_missing}')

                logger.info(f'{chat_id}: {insta_handle} CHECK_RESULT: {output_list}')


                if output_list:
                    if len(output_list) > 1:
                        list_to_check = '\nwww.instagram.com/' + '\nwww.instagram.com/'.join(output_list)
                    else:
                        list_to_check = '\nwww.instagram.com/' + output_list[0]

                    check_message = name + '\ncheck these users:\n' + list_to_check

                    logger_check_list = ' '.join(output_list)
                    logger.info(f'{chat_id}: {insta_handle} engagements missing: {logger_check_list}')

                else:
                    check_message = name + '\nyou engaged with everyone participating so far, great work!'

                check_response = bot.sendMessage(chat_id, check_message, reply_to_message_id=update.message.message_id, disable_web_page_preview=True)

                time_of_deletion = datetime.now() + timedelta(seconds=150)
                job_queue.run_once(delete_check_message, time_of_deletion, context=[chat_id, update.message.message_id, user_id], name='delete check message from user')
                job_queue.run_once(delete_check_message, time_of_deletion, context=[chat_id, check_response.message_id], name='delete check response from bot')

            else:
                bot.delete_message(chat_id=update.message.chat_id, message_id=update.message.message_id)
                logger.info(f'{chat_id}: deleted /check message from non-participating user')
                bot.sendMessage(chat_id, 'The /check command is only available for participants of the drop')

        else:
            logger.info(f'{chat_id}: deleted /check message from non-participating user')
            bot.sendMessage(chat_id, 'You are not participating in this round. Please make sure you posted the check command to the correct group.', reply_to_message_id=update.message.message_id)
    else:
        bot.sendMessage(chat_id, 'The /check command only works when a round is in progress.')
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
# @async1
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
    api1 = InstagramAPI(INSTA_USERNAME, INSTA_PASSWORD)
    api2 = InstagramAPI(INSTA_USERNAME2, INSTA_PASSWORD2)
    api3 = InstagramAPI(INSTA_USERNAME3, INSTA_PASSWORD3)
    sleep(1)
    api1.login()
    sleep(1)
    api2.login()
    sleep(1)
    api3.login()
    sleep(1)
    apis = cycle([api1, api2, api3])

    logger.info(f'Instagram account(s): ready')


    # TODO если надо будет обновлять конфиг в лайве
    # wm = pyinotify.WatchManager()
    # s1 = pyinotify.Stats()  # Stats is a subclass of ProcessEvent
    # notifier1 = pyinotify.ThreadedNotifier(wm, default_proc_fun=Identity(s1))
    # notifier1.start()
    # wm.add_watch(FOLDER_PATH, pyinotify.IN_MODIFY, rec=True, auto_add=True)
    # logger.info('Watchdog: ready')
    setup()
