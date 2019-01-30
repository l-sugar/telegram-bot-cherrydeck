from InstagramAPI import *
from logging import *
import json
from time import sleep
#
#
api = InstagramAPI('ovleng4', 'qwe228rty')
api.login()
# #
# # post_likers = []
# # max_id=""
# # api.searchUsername('ricawenzel')
# # user_id = api.LastJson.get("user", "").get("pk", "")
# # sleep(1)
# # api.getUserFeed(user_id)
# # post_id = str(api.LastJson.get("items", "")[0].get("pk", ""))
# # sleep(1)
# # api.getMediaLikers(post_id)
# # # for i in api.LastJson["users"]:
# # #     post_likers.append(i.get("username"))
# # #print(json.dumps(api.LastJson, indent=4, sort_keys=True))
# # print(json.dumps(api.LastJson.get("username", "")[], indent=3, sort_keys=True))
# api.searchUsername('felsenwald')
# print(json.dumps(api.LastJson, indent=4, sort_keys=True))
for x in range(1,500):
    api.searchUsername('cherrydeck')
    print(x)
    print(json.dumps(api.LastJson.get("status"), indent=3, sort_keys=True))
    sleep(0.1)
