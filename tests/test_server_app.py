"""server.app, the WSGI entry Vercel runs, and the shared password in front of every page and API call."""

import io
import time
from wsgiref.util import setup_testing_defaults
from wsgiref.validate import validator

import pytest

import server


@pytest.fixture
def root(tmp_path, monkeypatch, db):
    monkeypatch.setattr(server, "DATA_ROOT", tmp_path)
    monkeypatch.delenv("SITE_PASSWORD", raising=False)
    return tmp_path


def call(path, method="GET", body=b"", cookie=None, query="", **headers):
    environ = {
        "REQUEST_METHOD": method,
        "SCRIPT_NAME": "",
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "wsgi.input": io.BytesIO(body),
    }
    if body:
        environ["CONTENT_LENGTH"] = str(len(body))
        environ["CONTENT_TYPE"] = "application/x-www-form-urlencoded"
    if cookie:
        environ["HTTP_COOKIE"] = cookie
    environ.update({f"HTTP_{k.upper()}": v for k, v in headers.items()})
    setup_testing_defaults(environ)
    got = {}

    def start_response(status, headers, exc_info=None):
        got["status"], got["headers"] = status, dict(headers)

    it = validator(server.app)(environ, start_response)
    try:
        out = b"".join(it)
    finally:
        it.close()  # type: ignore[attr-defined]  # as a WSGI server does
    return got["status"], got["headers"], out


@pytest.mark.usefixtures("root")
def test_without_a_password_the_console_is_open():
    status, headers, body = call("/api/meta")
    assert status == "200 OK" and headers["Content-Type"] == "application/json"
    assert b'"password": false' in body and b'"rooms": 0' in body
    assert call("/")[0] == "200 OK"


@pytest.mark.usefixtures("root")
def test_with_a_password_everything_waits_for_a_session(monkeypatch):
    monkeypatch.setenv("SITE_PASSWORD", "correct horse")
    assert call("/api/meta")[0] == "401 Unauthorized"
    status, headers, _ = call("/")
    assert status == "303 See Other" and headers["Location"] == "/login"
    status, _, page = call("/login")
    assert status == "200 OK" and b'name="password"' in page

    status, headers, _ = call("/login", "POST", b"password=wrong")
    assert headers["Location"] == "/login?error=1" and "Set-Cookie" not in headers

    status, headers, _ = call("/login", "POST", b"password=correct+horse", x_forwarded_proto="https")
    assert headers["Location"] == "/"
    cookie = headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie and "Secure" in cookie
    session = cookie.split(";")[0]
    status, _, body = call("/api/meta", cookie=session)
    assert status == "200 OK" and b'"password": true' in body

    _, headers, _ = call("/logout", cookie=session)
    assert headers["Location"] == "/login" and "Max-Age=0" in headers["Set-Cookie"]


@pytest.mark.usefixtures("root")
def test_a_session_is_refused_once_expired_tampered_or_the_password_changes(monkeypatch):
    monkeypatch.setenv("SITE_PASSWORD", "one")
    good = server.session_value()
    assert server.valid_session(good)
    assert not server.valid_session(server.session_value(now=time.time() - 31 * 86400))  # expired
    exp, _, sig = good.partition(".")
    assert not server.valid_session(f"{int(exp) + 999999}.{sig}")  # a longer expiry it did not sign
    assert not server.valid_session("garbage")
    monkeypatch.setenv("SITE_PASSWORD", "two")
    assert not server.valid_session(good)


def test_paths_and_errors_survive_the_wsgi_adapter(root, db):
    (root / "Zürich Fund - Credit" / "_index").mkdir(parents=True)
    (root / "Zürich Fund - Credit" / "_index" / "pages.jsonl").write_text("")
    path = b"/api/fs".decode("latin-1")
    status, _, body = call(path, query="path=" + "Z%C3%BCrich%20Fund%20-%20Credit")
    assert status == "200 OK" and b'"path": "Z\\u00fcrich Fund - Credit"' in body
    assert call("/api/nowhere")[0] == "404 Not Found"
    assert call("/api/meta", "PATCH")[0] == "405 Method Not Allowed"
