def handle_from_link(link):
    match = re.search('nstagram.com/[^/?]+', link)
    username = match.group().rsplit('/', maxsplit=1)[-1]
    return username




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
                for i in likers_missing:
                    list.append(str(i))
                for j in comment_missing:
                    list.append(str(j))
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

            logger.info(f'Received /check command from {insta_handle}')
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
            participating_insta_links = [y for y in [x for x in data]]

            # for i in data:
            #     for j in i:
            #         participating_insta_links.append(j)
            logger.warning(f'PARTICIPATING INSTA LINKS ARE: {participating_insta_links}')

            check_result = get_links_to_check(api, insta_handle, participating_insta_links)


            if check_result:
                if len(check_result) > 1:
                    list_to_check = '\nwww.instagram.com/' + '\nwww.instagram.com/'.join(check_result)
                else:
                    list_to_check = '\nwww.instagram.com/' + check_result[0]

                check_message = name + '\ncheck these users:\n' + list_to_check

                logger_check_list = ' '.join(check_result)
                logger.info(f'{insta_handle} engagements missing: {logger_check_list}')

            else:
                check_message = name + '\n you engaged with everyone participating so far, great work!'

            check_response = bot.sendMessage(update.message.chat_id, check_message, reply_to_message_id=update.message.message_id, disable_web_page_preview=True)

            time_of_deletion = datetime.now() + timedelta(seconds=60)
            job_queue.run_once(delete_bot_message, time_of_deletion, context=[check_response.chat_id, check_response.message_id], name='delete check response from bot')
            job_queue.run_once(delete_check_message, time_of_deletion, context=[update.message.chat_id, update.message.message_id, update.message.from_user.id], name='delete check message from user')

        else:
            bot.delete_message(chat_id=update.message.chat_id, message_id=update.message.message_id)
            logger.info('deleted /check message from non-participating user')
            bot.sendMessage(update.message.chat_id, 'The /check command is only available for participants of the drop')
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
