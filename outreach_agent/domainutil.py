from urllib.parse import urlparse


def normalize_domain(url_or_email: str) -> str:
    """Normalize a domain, URL, or email to a bare registrable domain.

    Handles:
    - http://www.example.com/path -> example.com
    - https://EXAMPLE.COM -> example.com
    - example.com -> example.com
    - user@example.com -> example.com

    Returns lowercase bare domain, or empty string if unparseable.
    """
    if not url_or_email:
        return ""

    url_or_email = url_or_email.strip()

    # Handle email addresses
    if "@" in url_or_email:
        domain = url_or_email.split("@")[-1]
    else:
        # Try to parse as URL
        if "://" not in url_or_email:
            domain = url_or_email
        else:
            parsed = urlparse(url_or_email)
            domain = parsed.netloc or parsed.path

    # Strip www., lowercase, remove trailing slash/path
    domain = domain.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    domain = domain.split("/")[0]  # Remove path if present
    domain = domain.split(":")[0]  # Remove port if present

    return domain
