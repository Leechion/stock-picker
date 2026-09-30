"""Core infrastructure.

Importing this package installs the httpx proxy-environment workaround, which
must happen before any module builds an httpx client. See
``app/core/http.py`` for the full explanation of the macOS ``NO_PROXY`` bug.
"""

from app.core.http import install_proxy_env_fix

# Apply at import time: many modules build clients at call time, but some
# (and third-party libs such as akshare) read proxy config as soon as they are
# imported, so the environment must be sane as early as possible.
install_proxy_env_fix()

__all__ = ["install_proxy_env_fix"]
