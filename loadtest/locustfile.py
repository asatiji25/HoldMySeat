from locust import HttpUser, task, between
import uuid

class HoldMySeatUser(HttpUser):
    wait_time = between(0.2, 1.0)

    def on_start(self):
        self.user_id = "load-" + uuid.uuid4().hex[:12]
        response = self.client.post("/queue/join", json={"user_id": self.user_id})
        if response.status_code in (200, 201):
            self.queue_number = response.json().get("queue_number")
        else:
            self.queue_number = None

    @task(3)
    def view_seats(self):
        self.client.get("/seats?status=AVAILABLE", name="/seats?status=AVAILABLE")

    @task(1)
    def view_queue(self):
        self.client.get(f"/queue/{self.user_id}", name="/queue/{user_id}")

    @task(1)
    def view_metrics(self):
        self.client.get("/metrics/contention", name="/metrics/contention")
