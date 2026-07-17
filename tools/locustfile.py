"""Locust load test for Finn Help API.

Usage:
    uv sync --group loadtest
    locust -f tools/locustfile.py --host=http://localhost:8000
"""

from locust import HttpUser, between, task


class FinnHelpUser(HttpUser):
    wait_time = between(1, 5)

    def on_start(self) -> None:
        resp = self.client.post("/api/auth/register", json={
            "username": "loadtest",
            "password": "LoadTest123",
            "risk_profile": "balanced",
        })
        if resp.status_code == 200:
            data = resp.json()
            self.token = data.get("access_token", "")
        else:
            self.token = ""
            resp = self.client.post("/api/auth/login", json={
                "username": "loadtest",
                "password": "LoadTest123",
            })
            if resp.status_code == 200:
                self.token = resp.json().get("access_token", "")

    @task(3)
    def health(self) -> None:
        self.client.get("/api/health")

    @task(2)
    def instruments(self) -> None:
        self.client.get("/api/instruments", headers=self._auth_header())

    @task(1)
    def portfolio(self) -> None:
        self.client.get("/api/portfolio", headers=self._auth_header())

    @task(1)
    def me(self) -> None:
        self.client.get("/api/auth/me", headers=self._auth_header())

    def _auth_header(self) -> dict[str, str]:
        if self.token:
            return {"Authorization": f"Bearer {self.token}"}
        return {}
