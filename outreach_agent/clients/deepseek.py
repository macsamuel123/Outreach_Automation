from typing import Optional

import requests

from .http_base import NonRetriableAPIError, RetriableAPIError, build_session, retry_on_transient


class DeepSeekClient:
    """Client for DeepSeek API (OpenAI-compatible chat completions)."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-chat",
        session: Optional[requests.Session] = None,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.session = session or build_session()

    @retry_on_transient(max_attempts=4)
    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        response_format_json: bool = False,
        timeout_s: int = 60,
    ) -> str:
        """Call DeepSeek chat completions API.

        Args:
            system_prompt: System message
            user_prompt: User message
            temperature: Sampling temperature (0-1)
            response_format_json: Request JSON output format
            timeout_s: Request timeout

        Returns:
            The response text

        Raises:
            RetriableAPIError on transient failures
            NonRetriableAPIError on auth/validation errors
        """
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
        }

        if response_format_json:
            body["response_format"] = {"type": "json_object"}

        try:
            resp = self.session.post(url, json=body, headers=headers, timeout=timeout_s)
        except requests.RequestException as e:
            raise RetriableAPIError(f"DeepSeek request failed: {e}")

        if resp.status_code in (401, 403):
            raise NonRetriableAPIError(f"Auth failed: {resp.status_code}")
        if resp.status_code == 400:
            raise NonRetriableAPIError(f"Bad request: {resp.text}")
        if resp.status_code >= 500:
            raise RetriableAPIError(f"Server error: {resp.status_code}")

        try:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return content
        except (KeyError, ValueError, IndexError) as e:
            raise RetriableAPIError(f"Invalid response format: {e}")
