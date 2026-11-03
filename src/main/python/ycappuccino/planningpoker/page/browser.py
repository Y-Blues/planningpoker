"""The two things the page asks the browser itself (Pyodide): the page's absolute address, a strong random secret."""

import secrets


def page_address(location: str) -> str:
    """the absolute URL of a location of this page (path, search, hash), as a link to share"""
    try:
        from js import location as browser  # Pyodide only

        return str(browser.origin) + location
    except ImportError:
        return location


def new_secret() -> str:
    """256 random bits (os.urandom: the browser's crypto.getRandomValues under Pyodide)"""
    return secrets.token_urlsafe(32)
