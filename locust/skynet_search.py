from locust import HttpLocust, TaskSet, task
  
class SkynetTasks(TaskSet):
    def on_start(self):
        pass

    @task
    def search(self):
        self.client.post("/skynet/api/domain/search", {
                 'province': '河北省',
                 'city': '石家庄市',
                 'district': '桥西区',
                 'latitude': 38.021019,
                 'longitude': 114.435741
             })

class SkynetUser(HttpLocust):
    task_set = SkynetTasks
    host = 'https://www.video110.cn:8030' 
    min_wait = 5000
    max_wait = 15000
