from locust import HttpLocust, TaskSet, task

'''
对用户数量设置大的测试，需要设置相应的LIMIT_NOFILE:
/etc/security/limits.conf 

或：
ulimit -n 10000
'''
class SkynetSearchTasks(TaskSet):
    def on_start(self):
        self.login()

    def login(self):
        #在这里登录
        pass

    def on_stop(self):
        self.logout()

    def logout(self):
        #在这里注销登录
        pass

    # 10是权重，当有多个任务的时候，权重越大，执行的次数越多
    @task(10)
    def search(self):
        self.client.post("/skynet/api/domain/search", {
                 'province': '河北省',
                 'city': '石家庄市',
                 'district': '桥西区',
                 'latitude': 38.021019,
                 'longitude': 114.435741
             })

class SkynetSearchUser(HttpLocust):
    # step 1: task_set必须指向一个TaskSet类
    task_set = SkynetSearchTasks

    # replaced with --host in locust command line
    host = 'https://www.video110.cn:8030' 

    # step 2: 设置每个仿真用户的两个访问间最小/最大等待时间，缺省是1秒（1000）
    min_wait = 1000
    max_wait = 10000

'''
#可以从同一个文件同时跑多个locust用户： 
#locust -f skynet_search.py SkynetSearchUser SkynetAdminUser

class SkynetAdminUser:
    pass
'''
