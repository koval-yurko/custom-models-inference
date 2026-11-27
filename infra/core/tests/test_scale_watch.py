import unittest
from urllib.error import HTTPError

import scale_watch as sw


def fake_get(answers):
    """get(url, auth) for the tests: answers maps a URL to a dict, or to an int (an HTTP error status)."""
    calls = []

    def get(url, auth):
        calls.append((url, auth))
        a = answers[url]
        if isinstance(a, int):
            raise HTTPError(url, a, "err", None, None)
        return a

    get.calls = calls
    return get


class RunpodCounts(unittest.TestCase):
    def test_up_workers_are_idle_or_running_with_an_uptime(self):
        # Measured 2026-11-23: a FlashBoot worker that has stopped stays in the list as IDLE, with no uptimeSeconds.
        get = fake_get({
            "https://api.runpod.io/v2/serverless": {"endpoints": [{"id": "ep1", "name": "llm-a"}, {"id": "ep2", "name": "b"}]},
            "https://api.runpod.io/v2/serverless/ep1/workers": {"workers": [
                {"id": "w1", "status": "RUNNING", "uptimeSeconds": 21},
                {"id": "w2", "status": "IDLE", "uptimeSeconds": 400},
                {"id": "w3", "status": "INITIALIZING", "uptimeSeconds": 5},
            ]},
            "https://api.runpod.io/v2/serverless/ep2/workers": {"workers": [{"id": "w4", "status": "IDLE", "startedAt": "2026-11-23T07:58:08Z"}]},
        })
        self.assertEqual(sw.runpod_counts("k", {"runpod/ep1": 1}, get), {"runpod/ep1": ("llm-a", 2), "runpod/ep2": ("b", 0)})
        self.assertEqual(get.calls[0][1], "Bearer k")

    ONE_UP = {
        "https://api.runpod.io/v2/serverless": {"endpoints": [
            {"id": "ep1", "name": "llm-b", "requestUrls": {"health": "https://ep1.api.runpod.ai/health"}}]},
        "https://api.runpod.io/v2/serverless/ep1/workers": {"workers": [{"id": "w1", "status": "RUNNING", "uptimeSeconds": 60}]},
    }

    def probe(self, answer):
        calls = []

        def p(url, auth):
            calls.append((url, auth))
            return answer
        p.calls = calls
        return p

    def test_a_started_worker_is_not_ready_until_health_answers_200(self):
        # Measured 2026-11-24: LLM-B got "is ready" at 09:33 from the worker uptime, and its model never answered.
        loading = self.probe(False)
        self.assertEqual(sw.runpod_counts("k", {"runpod/ep1": 0}, fake_get(self.ONE_UP), loading), {"runpod/ep1": ("llm-b", 0)})
        self.assertEqual(loading.calls, [("https://ep1.api.runpod.ai/health", "Bearer k")])
        self.assertEqual(sw.runpod_counts("k", {"runpod/ep1": 0}, fake_get(self.ONE_UP), self.probe(True)), {"runpod/ep1": ("llm-b", 1)})

    def test_no_probe_once_ready_or_when_no_worker_is_up(self):
        # A probe at 0 workers would start a GPU; a probe every minute after ready would stop the scale to 0.
        p = self.probe(False)
        self.assertEqual(sw.runpod_counts("k", {"runpod/ep1": 1}, fake_get(self.ONE_UP), p), {"runpod/ep1": ("llm-b", 1)})
        down = {**self.ONE_UP, "https://api.runpod.io/v2/serverless/ep1/workers": {"workers": [{"id": "w1", "status": "IDLE"}]}}
        self.assertEqual(sw.runpod_counts("k", None, fake_get(down), p), {"runpod/ep1": ("llm-b", 0)})
        self.assertEqual(p.calls, [])

    def test_own_image_endpoints_that_post_to_slack_get_no_request(self):
        # Measured 2026-11-27: the /health probe reset the 300 s idle timer of LLM-B, and the GPU ran 5 more minutes.
        own = {"https://api.runpod.io/v2/serverless": {"endpoints": [
            {"id": "ep1", "name": "llm-b", "env": {"SLACK_TITLE": "LLM-B on Runpod", "PORT": "8000"}}]}}
        get, p = fake_get(own), self.probe(True)
        self.assertEqual(sw.runpod_counts("k", {"runpod/ep1": 0}, get, p), {})
        self.assertEqual(len(get.calls), 1)
        self.assertEqual(p.calls, [])


class Events(unittest.TestCase):
    def test_first_run_only_records(self):
        self.assertEqual(sw.events(None, {"runpod/ep1": ("llm-a", 1)}), [])

    def test_up_and_down(self):
        prev = {"runpod/ep1": 0, "runpod/ep2": 1}
        cur = {"runpod/ep1": ("llm-a", 1), "runpod/ep2": ("llm-b", 0)}
        self.assertEqual(sw.events(prev, cur), [
            "scale-watch: runpod ep1 ready (llm-a)",
            "scale-watch: runpod ep2 scaled to 0 (llm-b)",
        ])

    def test_more_replicas_is_no_event(self):
        self.assertEqual(sw.events({"runpod/ep1": 1}, {"runpod/ep1": ("llm-a", 2)}), [])

    def test_new_endpoint_that_is_up_is_ready(self):
        self.assertEqual(sw.events({}, {"runpod/ep9": ("n", 1)}), ["scale-watch: runpod ep9 ready (n)"])

    def test_the_down_line_does_not_contain_the_ready_text(self):
        # The Slack alerts match a substring of the line: "scale-watch: <platform> <id> ready" must not match a down line.
        down = sw.events({"runpod/ep1": 1}, {"runpod/ep1": ("ready", 0)})[0]
        self.assertNotIn("scale-watch: runpod ep1 ready", down)


class NextState(unittest.TestCase):
    def test_a_failed_platform_keeps_its_old_counts(self):
        prev = {"runpod/ep1": 1, "other/x1": 0}
        cur = {"other/x1": ("x", 1)}
        self.assertEqual(sw.next_state(prev, cur, failed={"runpod"}), {"runpod/ep1": 1, "other/x1": 1})


class Commit(unittest.TestCase):
    def test_lines_come_out_after_the_state_is_saved(self):
        self.assertEqual(sw.commit(["scale-watch: runpod ep1 ready (x)"], lambda: None), ["scale-watch: runpod ep1 ready (x)"])

    def test_a_run_that_lost_the_race_prints_nothing(self):
        # Two runs can overlap (a late start). Only the run whose conditional save wins prints the change.
        def lost():
            raise sw.Conflict()
        self.assertEqual(sw.commit(["scale-watch: runpod ep1 ready (x)"], lost), [])


class Platforms(unittest.TestCase):
    def test_each_platform_is_a_name_an_env_var_and_a_reader(self):
        # main() loops over PLATFORMS; a 1-entry tuple without its trailing comma broke the live job (2026-11-23).
        self.assertTrue(sw.PLATFORMS)
        for name, env, fn in sw.PLATFORMS:
            self.assertIsInstance(name, str)
            self.assertTrue(env.endswith("_API_KEY"))
            self.assertTrue(callable(fn))


if __name__ == "__main__":
    unittest.main()
