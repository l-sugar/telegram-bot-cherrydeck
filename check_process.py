from collections import defaultdict

check_queue = defaultdict(list)

def add_to_check_queue(bot, update, job_queue):
    global check_queue

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
                check_queue[chat_id].append(insta_handle)
                logger.info(f'{chat_id}: Added {insta_handle} to check_queue')


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


def check_for_check_requests(bot, job):
    global check_queue
    chat_id = job.context[0]
    if len(check_queue[chat_id]) > 0:
        insta_handle = check_queue[chat_id][0]
        process_check_request(insta_handle)
    else:

        logger.info('no check requested')


def process_check_request(insta_handle):
    
