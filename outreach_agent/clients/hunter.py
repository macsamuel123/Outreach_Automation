import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

from .http_base import NonRetriableAPIError, RetriableAPIError, build_session


@dataclass
class HunterUsageState:
    """Track local Hunter API usage counters."""

    searches_this_month: int
    verifications_used_total: int
    month_key: str  # "YYYY-MM" for rollover detection


class QuotaExceeded(Exception):
    """Raised when a Hunter quota limit has been reached."""

    pass


def load_usage_state(
    path: Path = Path("state/hunter_usage.json"),
    seed_verifications_used: int = 0,
) -> HunterUsageState:
    """Load usage state from JSON, or create from seed values."""
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return HunterUsageState(**data)

    # Initialize from seed (usually config.yaml's hunter_limits.verifications_used)
    today = datetime.utcnow()
    month_key = f"{today.year:04d}-{today.month:02d}"

    return HunterUsageState(
        searches_this_month=0,
        verifications_used_total=seed_verifications_used,
        month_key=month_key,
    )


def save_usage_state(
    state: HunterUsageState, path: Path = Path("state/hunter_usage.json")
) -> None:
    """Save usage state to JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(state), f, indent=2)


class HunterClient:
    """Client for Hunter.io API (domain search and email verification)."""

    def __init__(
        self,
        api_key: str,
        usage_state: HunterUsageState,
        max_searches_per_month: int,
        max_verifications_total: int,
        session: Optional[requests.Session] = None,
        base_url: str = "https://api.hunter.io",
    ):
        self.api_key = api_key
        self.usage = usage_state
        self.max_searches_per_month = max_searches_per_month
        self.max_verifications_total = max_verifications_total
        self.session = session or build_session()
        self.base_url = base_url

        # Check for month rollover
        today = datetime.utcnow()
        current_month = f"{today.year:04d}-{today.month:02d}"
        if current_month != self.usage.month_key:
            self.usage.searches_this_month = 0
            self.usage.month_key = current_month

    def domain_search(self, domain: str, decision_maker_titles: list[str]) -> list[dict]:
        """Search for contacts at a domain.

        Filters results to decision-maker titles. Increments search counter on success.

        Returns a list of dicts: {name, position, email, confidence, ...}

        Raises:
            QuotaExceeded if monthly search limit reached
            RetriableAPIError on API failures
            NonRetriableAPIError on auth errors
        """
        if self.usage.searches_this_month >= self.max_searches_per_month:
            raise QuotaExceeded(
                f"Hunter search quota exceeded: {self.usage.searches_this_month} / "
                f"{self.max_searches_per_month}"
            )

        url = f"{self.base_url}/v2/domain-search"

        try:
            resp = self.session.get(
                url,
                params={
                    "domain": domain,
                    "api_key": self.api_key,
                },
                timeout=30,
            )
        except requests.RequestException as e:
            raise RetriableAPIError(f"Hunter domain search failed: {e}")

        if resp.status_code in (401, 403):
            raise NonRetriableAPIError(f"Auth failed: {resp.status_code}")
        if resp.status_code >= 500:
            raise RetriableAPIError(f"Server error: {resp.status_code}")

        try:
            data = resp.json()
            emails = data["data"]["emails"]
        except (KeyError, ValueError) as e:
            raise RetriableAPIError(f"Invalid response: {e}")

        # Filter to decision-maker titles
        titles_lower = [t.lower() for t in decision_maker_titles]
        candidates = []

        for email_obj in emails:
            position = email_obj.get("position", "").lower()
            department = email_obj.get("department", "").lower()

            if any(title in position or title in department for title in titles_lower):
                candidates.append(
                    {
                        "name": email_obj.get("first_name", "")
                        + " "
                        + email_obj.get("last_name", ""),
                        "position": email_obj.get("position", ""),
                        "email": email_obj.get("value", ""),
                        "confidence": email_obj.get("confidence", 0),
                        "raw": email_obj,
                    }
                )

        # Increment counter on any successful response (even if no candidates)
        self.usage.searches_this_month += 1

        return candidates

    def verify_email(self, email: str) -> dict:
        """Verify an email address.

        Returns: {status: 'valid'|'invalid'|'risky'|'unknown', score: int, raw: {...}}

        Raises:
            QuotaExceeded if verification quota exceeded
            RetriableAPIError on API failures
            NonRetriableAPIError on auth errors
        """
        if self.usage.verifications_used_total >= self.max_verifications_total:
            raise QuotaExceeded(
                f"Hunter verification quota exceeded: {self.usage.verifications_used_total} / "
                f"{self.max_verifications_total}"
            )

        url = f"{self.base_url}/v2/email-verifier"

        try:
            resp = self.session.get(
                url,
                params={
                    "email": email,
                    "api_key": self.api_key,
                },
                timeout=30,
            )
        except requests.RequestException as e:
            raise RetriableAPIError(f"Hunter email verify failed: {e}")

        if resp.status_code in (401, 403):
            raise NonRetriableAPIError(f"Auth failed: {resp.status_code}")
        if resp.status_code >= 500:
            raise RetriableAPIError(f"Server error: {resp.status_code}")

        try:
            data = resp.json()
            result = data["data"]["result"]
            score = data["data"]["score"]
        except (KeyError, ValueError) as e:
            raise RetriableAPIError(f"Invalid response: {e}")

        # Increment counter on any completed API call
        self.usage.verifications_used_total += 1

        return {
            "status": result,
            "score": score,
            "raw": data["data"],
        }
