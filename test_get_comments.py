# test get insta_comments

from InstagramAPI import InstagramAPI
import logging

api = InstagramAPI('ovleng4', 'qwe228rty')

api.login()

# def get_pic_engagements(user):
#     try:
#         api.searchUsername(user)
#         id = str(api.LastJson.get('user', "").get("pk", ""))
#         api.getUserFeed(id)
#         post_id = str(api.LastJson.get('items', "")[0].get("pk", ""))
#         api.getMediaLikers(post_id)
#         likers_handles = []
#         for i in api.LastJson['users']:
#             print(str(i.get('username', "")))
#     except Exception as e:
#         logging.exception(e)
#         raise
#
# get_pic_engagements('cherrydeck')

def getComments(api, post_id):

    accounts_to_test = ['nikolasgogstad', 'jan_niklas_kowalk', 'stefan_p_photography', 'alfonso_bricegno', 'highluxphoto', 'oliverkielstrup', 'imjoanamaria', 'dominika_scheibinger', 'rettekraudmets', 'jmstudio.dk', 'odouglas50', 'ricawenzel', 'danielanunesf', 'cherrydeck', 'andybattportfolio', 'with_feathers', 'basso2012', 'afonsomolinar', 'jack_and_kie', 'didierbarontini', 'Alexander_dhiet', 'hdc101' ]
    comments = []
    next_max_id = True
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
                    logging.warning('error while getting username from comment')
                    logging.exception(e)
                    raise
            next_max_id = api.LastJson.get('next_max_id', '')
        except Exception as e:
            logging.warning('error while getting comments')
            logging.exception(e)
            raise
    for user in accounts_to_test:
        if user not in comments:
            print(user)


getComments(api, '1961846907498044758')

# def getTotalFollowers(api, user_id):
#     """
#     Returns the list of followers of the user.
#     It should be equivalent of calling api.getTotalFollowers from InstagramAPI
#     """
#
#     followers = []
#     next_max_id = True
#     while next_max_id:
#         # first iteration hack
#         if next_max_id is True:
#             next_max_id = ''
#
#         _ = api.getUserFollowers(user_id, maxid=next_max_id)
#         followers.extend(api.LastJson.get('users', []))
#         next_max_id = api.LastJson.get('next_max_id', '')
#     print(followers)
#
# getTotalFollowers(api, '17950676368225416')

# from InstagramAPI import InstagramAPI
# import time
# from datetime import datetime
#
# user_id = '17950676368225416'
#
#
# API.getUsernameInfo(user_id)
# API.LastJson
# following = []
# next_max_id = True
# while next_max_id:
#     # first iteration hack
#     if next_max_id is True:
#         next_max_id = ''
#     _ = API.getUserFollowings(user_id, maxid=next_max_id)
#     following.extend(API.LastJson.get('users', []))
#     next_max_id = API.LastJson.get('next_max_id', '')
#
# for user in following:
#     print(user)
