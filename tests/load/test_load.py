import logging

from locust import HttpUser, between, events, task
from locust.runners import MasterRunner

logger = logging.getLogger(__name__)


class APILoadUser(HttpUser):
    wait_time = between(0.1, 0.5)

    @task(10)
    def list_propositions(self):
        with self.client.get(
            "/api/v1/propositions/",
            catch_response=True,
            name="/propositions [list]"
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Got {resp.status_code}")

    @task(5)
    def list_propositions_with_query(self):
        with self.client.get(
            "/api/v1/propositions/?q=saude",
            catch_response=True,
            name="/propositions [search]"
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Got {resp.status_code}")

    @task(3)
    def get_proposition_detail(self):
        import random
        prop_id = random.randint(1, 1000)
        with self.client.get(
            f"/api/v1/propositions/{prop_id}",
            catch_response=True,
            name="/propositions [detail]"
        ) as resp:
            if resp.status_code in (200, 404):
                resp.success()
            else:
                resp.failure(f"Got {resp.status_code}")

    @task(2)
    def list_parliamentarians(self):
        with self.client.get(
            "/api/v1/legislatures/parliamentarians",
            catch_response=True,
            name="/parliamentarians"
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Got {resp.status_code}")

    @task(2)
    def list_themes(self):
        with self.client.get(
            "/api/v1/taxonomy/themes",
            catch_response=True,
            name="/themes"
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Got {resp.status_code}")

    @task(1)
    def list_parties(self):
        with self.client.get(
            "/api/v1/legislatures/parties",
            catch_response=True,
            name="/parties"
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Got {resp.status_code}")


class MatcherLoadUser(HttpUser):
    wait_time = between(0.05, 0.2)

    @task
    def match_document(self):
        import random
        prop_id = random.randint(1, 900)
        with self.client.get(
            f"/api/v1/propositions/{prop_id}",
            catch_response=True,
            name="matcher"
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Got {resp.status_code}")


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    logger.info("Load test starting")
    if isinstance(environment.runner, MasterRunner):
        logger.info("Running in distributed mode")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    logger.info("Load test completed")
    stats = environment.stats
    logger.info(
        f"Total requests: {stats.total.num_requests}, "
        f"Failures: {stats.total.num_failures}, "
        f"p95: {stats.total.get_response_time_percentile(0.95)}ms"
    )
