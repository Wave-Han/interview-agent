# tests/conftest.py
# Test-session sqlite shim: FastAPI's TestClient serves requests on a
# worker thread while fixtures create sqlite connections on the pytest
# main thread; sqlite3 rejects any cross-thread use of a connection
# created with the default check_same_thread=True. Make every test
# connection thread-flexible so shared-conn fixtures work under
# TestClient. Production code is untouched (this module is test-only)
# and the single-threaded CLI-style tests behave identically.
import sqlite3

_real_connect = sqlite3.connect


def _connect_thread_flexible(*args, **kwargs):
    kwargs.setdefault("check_same_thread", False)
    return _real_connect(*args, **kwargs)


sqlite3.connect = _connect_thread_flexible
