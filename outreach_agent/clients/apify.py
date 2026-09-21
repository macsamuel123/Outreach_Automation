import time
from typing import Optional

import requests

from .http_base import NonRetriableAPIError, RetriableAPIError, build_session


class ApifyClient:
    """Client for Apify REST API (actor runs and dataset retrieval)."""

    def __init__(
        self,
        api_token: str,
        session: Optional[requests.Session] = None,
        base_url: str = "https://api.apify.com",
    ):
        self.api_token = api_token
        self.base_url = base_url
        self.session = session or build_session()

    def run_actor_sync(
        self,
        actor_id: str,
        run_input: dict,
        poll_interval_s: int = 5,
        timeout_s: int = 600,
    ) -> str:
        """Run an actor synchronously and return the dataset ID.

        Args:
            actor_id: Actor ID (e.g., "username/actor-name")
            run_input: Input dict for the actor
            poll_interval_s: How often to poll status (seconds)
            timeout_s: Overall timeout (seconds)

        Returns:
            dataset_id on success

        Raises:
            RetriableAPIError on FAILED/TIMED-OUT status
            NonRetriableAPIError on 401/404 auth/not-found errors
        """
        # POST /v2/acts/{actor_id}/runs
        url = f"{self.base_url}/v2/acts/{actor_id}/runs"
        headers = {"Authorization": f"Bearer {self.api_token}"}

        try:
            resp = self.session.post(url, json=run_input, headers=headers, timeout=30)
        except requests.RequestException as e:
            raise RetriableAPIError(f"Failed to start actor run: {e}")

        if resp.status_code in (401, 403):
            raise NonRetriableAPIError(f"Auth failed: {resp.status_code}")
        if resp.status_code == 404:
            raise NonRetriableAPIError(f"Actor not found: {actor_id}")
        if resp.status_code >= 500:
            raise RetriableAPIError(f"Server error: {resp.status_code}")

        try:
            data = resp.json()
            run_id = data["data"]["id"]
        except (KeyError, ValueError) as e:
            raise RetriableAPIError(f"Invalid response: {e}")

        # Poll until terminal state
        start_time = time.time()
        while time.time() - start_time < timeout_s:
            run_url = f"{self.base_url}/v2/actor-runs/{run_id}"
            try:
                resp = self.session.get(run_url, headers=headers, timeout=30)
            except requests.RequestException as e:
                raise RetriableAPIError(f"Poll failed: {e}")

            if resp.status_code >= 500:
                raise RetriableAPIError(f"Poll server error: {resp.status_code}")

            try:
                data = resp.json()
                status = data["data"]["status"]
                dataset_id = data["data"].get("defaultDatasetId")
            except (KeyError, ValueError) as e:
                raise RetriableAPIError(f"Invalid poll response: {e}")

            if status == "SUCCEEDED":
                if not dataset_id:
                    raise RetriableAPIError("Run succeeded but no dataset_id")
                return dataset_id
            elif status in ("FAILED", "ABORTED", "TIMED-OUT"):
                raise RetriableAPIError(f"Run {status}: {data['data'].get('statusMessage')}")

            time.sleep(poll_interval_s)

        raise RetriableAPIError(f"Run timed out after {timeout_s}s")

    def get_dataset_items(
        self, dataset_id: str, limit: int = 1000, offset: int = 0
    ) -> list[dict]:
        """Fetch items from a dataset (paginated).

        Returns all items, paginating until fewer than `limit` items are returned.
        """
        url = f"{self.base_url}/v2/datasets/{dataset_id}/items"
        headers = {"Authorization": f"Bearer {self.api_token}"}

        all_items = []

        while True:
            try:
                resp = self.session.get(
                    url,
                    params={"limit": limit, "offset": offset},
                    headers=headers,
                    timeout=30,
                )
            except requests.RequestException as e:
                raise RetriableAPIError(f"Failed to fetch dataset items: {e}")

            if resp.status_code in (401, 403):
                raise NonRetriableAPIError(f"Auth failed: {resp.status_code}")
            if resp.status_code >= 500:
                raise RetriableAPIError(f"Server error: {resp.status_code}")

            try:
                items = resp.json()
            except ValueError as e:
                raise RetriableAPIError(f"Invalid response: {e}")

            all_items.extend(items)

            if len(items) < limit:
                break

            offset += limit

        return all_items
