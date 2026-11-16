"""tests/test_updater.py — Unit tests for updater.py (version comparison, network, integrity)."""

import hashlib
import os
import sys
import tempfile
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from updater import (_parse, _is_newer, _find_installer_asset, _fetch_latest,
                     _fetch_expected_sha256, _sha256_of, _friendly_error)


# ── _parse ────────────────────────────────────────────────────────────────────

def test_parse_standard_tag():
    assert _parse("v1.2.3") == (1, 2, 3)

def test_parse_no_v_prefix():
    assert _parse("2.0.0") == (2, 0, 0)

@pytest.mark.parametrize("tag", ["v1", "v1.2.3.4", "v1.0.25-rc1", "v1.0.24+build5", "latest", "", None, 5])
def test_parse_refuses_anything_but_major_minor_patch(tag):
    assert _parse(tag) is None


# ── _is_newer ─────────────────────────────────────────────────────────────────

def test_is_newer_detects_major_bump():
    assert _is_newer("v2.0.0", current="1.0.0") is True

def test_is_newer_detects_minor_bump():
    assert _is_newer("v1.1.0", current="1.0.0") is True

def test_is_newer_detects_patch_bump():
    assert _is_newer("v1.0.1", current="1.0.0") is True

def test_is_newer_same_version_is_not_newer():
    assert _is_newer("v1.0.0", current="1.0.0") is False

def test_is_newer_older_tag_is_not_newer():
    assert _is_newer("v0.9.9", current="1.0.0") is False

def test_is_newer_uses_version_py_default():
    from version import __version__
    # Current version is never newer than itself
    assert _is_newer(f"v{__version__}") is False


# ── _find_installer_asset ─────────────────────────────────────────────────────

def test_find_installer_asset_finds_exe():
    release = {
        "assets": [
            {"name": "Istari_Setup.exe", "browser_download_url": "https://example.com/setup.exe"},
            {"name": "source.zip",         "browser_download_url": "https://example.com/source.zip"},
        ]
    }
    assert _find_installer_asset(release) == "https://example.com/setup.exe"


def test_find_installer_asset_no_exe_returns_none():
    release = {
        "assets": [
            {"name": "source.tar.gz", "browser_download_url": "https://example.com/src.tar.gz"},
        ]
    }
    assert _find_installer_asset(release) is None


def test_find_installer_asset_empty_assets():
    assert _find_installer_asset({"assets": []}) is None


def test_find_installer_asset_missing_key():
    assert _find_installer_asset({}) is None


# ── _fetch_latest network error handling ──────────────────────────────────────

def test_fetch_latest_returns_none_on_url_error():
    """Network unavailable should return None, not raise."""
    with patch("updater.urllib.request.urlopen",
               side_effect=urllib.error.URLError("no network")):
        result = _fetch_latest("owner", "repo")
    assert result is None


def test_fetch_latest_returns_none_on_http_error():
    """HTTP 404 should return None, not raise."""
    with patch("updater.urllib.request.urlopen",
               side_effect=urllib.error.HTTPError(
                   url="", code=404, msg="Not Found", hdrs=None, fp=None)):
        result = _fetch_latest("owner", "repo")
    assert result is None


def test_fetch_latest_returns_none_on_timeout():
    """Timeout (subclass of URLError) should return None."""
    import socket
    with patch("updater.urllib.request.urlopen",
               side_effect=urllib.error.URLError(socket.timeout("timed out"))):
        result = _fetch_latest("owner", "repo")
    assert result is None


# ── SHA256 integrity check ─────────────────────────────────────────────────────

def _stub_downloader(url="https://example.com/Istari_Setup.exe"):
    """InstallerDownloader with its Qt signals and thread replaced by stubs."""
    from updater import InstallerDownloader

    d = InstallerDownloader.__new__(InstallerDownloader)
    d._url = url
    d._thread = MagicMock()
    d.progress = MagicMock()
    d.progress.emit = MagicMock()
    errors, finished = [], []
    d.error = MagicMock()
    d.error.emit = errors.append
    d.finished = MagicMock()
    d.finished.emit = finished.append
    d.cancelled = MagicMock()
    return d, errors, finished


def _fake_sidecar(text: str):
    resp = MagicMock()
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    resp.read.return_value = text.encode()
    return resp


# ── The checksum is mandatory: an unverified installer is never run ───────────

def test_missing_checksum_sidecar_refuses_to_install():
    """HTTP 404 for <url>.sha256 must stop the update, not install anyway.

    The downloaded exe is executed elevated, so "could not verify" has to fail
    closed — it used to be a log warning and the install went ahead.
    """
    d, errors, finished = _stub_downloader()

    with patch("updater.urllib.request.urlretrieve",
               side_effect=lambda url, dest, reporthook=None: open(dest, "wb").write(b"exe")):
        with patch("updater.urllib.request.urlopen",
                   side_effect=urllib.error.HTTPError(
                       url="", code=404, msg="Not Found", hdrs=None, fp=None)):
            d._run()

    assert finished == []
    assert len(errors) == 1
    assert "checksum" in errors[0].lower()


def test_checksum_fetch_network_error_refuses_to_install():
    """A network failure while reading the checksum is not "no checksum exists"."""
    d, errors, finished = _stub_downloader()

    with patch("updater.urllib.request.urlretrieve",
               side_effect=lambda url, dest, reporthook=None: open(dest, "wb").write(b"exe")):
        with patch("updater.urllib.request.urlopen",
                   side_effect=urllib.error.URLError("no network")):
            d._run()

    assert finished == []
    assert len(errors) == 1


def test_fetch_expected_sha256_parses_sidecar():
    with patch("updater.urllib.request.urlopen",
               return_value=_fake_sidecar("B61319AE8956  Istari_Setup.exe\n")):
        assert _fetch_expected_sha256("https://example.com/x.exe") == "b61319ae8956"


def test_fetch_expected_sha256_empty_body_is_none():
    with patch("updater.urllib.request.urlopen", return_value=_fake_sidecar("")):
        assert _fetch_expected_sha256("https://example.com/x.exe") is None


def test_sha256_of_matches_hashlib(tmp_path):
    p = tmp_path / "blob.bin"
    p.write_bytes(b"payload")
    assert _sha256_of(str(p)) == hashlib.sha256(b"payload").hexdigest()


def test_unverified_update_error_is_user_friendly():
    title, body = _friendly_error(
        "No SHA256 checksum published for this release, so the installer cannot be verified."
    )
    assert title == "Update Could Not Be Verified"
    assert "manually" in body


# ══ Regression tests: updater hardening (UP-1 … UP-11) ═══════════════════════

import http.server
import threading
import time

import updater
from updater import UpdateChecker, failure_text, _trim_notes, _cleanup_stale_update_dirs


def _assert_no_update_dirs(base):
    left = [n for n in os.listdir(base) if n.startswith("istari_update_")]
    assert left == [], f"temp update dirs left behind: {left}"


# ── UP-1: the app quits only after the installer really started ───────────────

def _installer_in(tmp_path):
    d = tmp_path / "istari_update_x"
    d.mkdir()
    exe = d / "Istari_Setup.exe"
    exe.write_bytes(b"x")
    return str(exe)


@pytest.fixture
def install_spy(monkeypatch):
    spy = MagicMock()
    spy.scheduled, spy.shown = [], []
    monkeypatch.setattr(updater.QTimer, "singleShot",
                        lambda ms, fn: spy.scheduled.append(fn))
    monkeypatch.setattr(updater, "_show_message",
                        lambda title, body, parent=None: spy.shown.append((title, body)))
    return spy


@pytest.fixture
def setup_probe(monkeypatch):
    """Fake the Win32 probes: the test sets .mutex / .exit_code; handles closed are recorded."""
    probe = MagicMock()
    probe.mutex, probe.exit_code, probe.closed = False, None, []
    monkeypatch.setattr(updater, "_setup_mutex_seen", lambda: probe.mutex)
    monkeypatch.setattr(updater, "_process_exit_code", lambda h: probe.exit_code)
    monkeypatch.setattr(updater, "_close_handle", probe.closed.append)
    return probe


def _poll_once(install_spy):
    """Run the next scheduled poll callback (the app's Qt timer tick)."""
    install_spy.scheduled.pop(0)()


@pytest.mark.parametrize("err", [1223, 5])
def test_failed_launch_keeps_the_app_running(monkeypatch, tmp_path, install_spy, err):
    monkeypatch.setattr(updater, "_launch_installer", lambda path: (err, None))
    exe, prog, quit_fn = _installer_in(tmp_path), MagicMock(), MagicMock()

    assert updater._start_install(exe, prog, quit_fn) is False

    assert install_spy.scheduled == []            # no quit, no polling
    quit_fn.assert_not_called()
    prog.done.assert_called_once_with(0)
    assert len(install_spy.shown) == 1            # the user is told
    assert f"error {err}" in install_spy.shown[0][1]
    assert not os.path.exists(exe)                # verified-but-unused installer removed


def test_started_loader_does_not_quit_before_setup_is_elevated(monkeypatch, tmp_path, install_spy, setup_probe):
    monkeypatch.setattr(updater, "_launch_installer", lambda path: (None, 77))
    quit_fn = MagicMock()

    assert updater._start_install(_installer_in(tmp_path), MagicMock(), quit_fn) is True
    for _ in range(5):                            # UAC prompt sits open: loader alive, no mutex
        _poll_once(install_spy)

    quit_fn.assert_not_called()
    assert len(install_spy.scheduled) == 1        # still polling, no timeout
    assert install_spy.shown == [] and setup_probe.closed == []


def test_mutex_seen_quits_and_closes_the_handle(monkeypatch, tmp_path, install_spy, setup_probe):
    monkeypatch.setattr(updater, "_launch_installer", lambda path: (None, 77))
    quit_fn = MagicMock()
    assert updater._start_install(_installer_in(tmp_path), MagicMock(), quit_fn) is True

    setup_probe.mutex = True
    _poll_once(install_spy)

    quit_fn.assert_called_once_with()
    assert setup_probe.closed == [77]
    assert install_spy.scheduled == [] and install_spy.shown == []


def test_declined_uac_exit_code_2_keeps_running_and_tells_the_user(monkeypatch, tmp_path, install_spy, setup_probe):
    monkeypatch.setattr(updater, "_launch_installer", lambda path: (None, 77))
    exe, prog, quit_fn = _installer_in(tmp_path), MagicMock(), MagicMock()
    assert updater._start_install(exe, prog, quit_fn) is True

    setup_probe.exit_code = 2
    _poll_once(install_spy)

    quit_fn.assert_not_called()
    prog.done.assert_called_once_with(0)
    assert len(install_spy.shown) == 1
    assert "administrator permission was not granted" in install_spy.shown[0][1]
    assert not os.path.exists(exe)
    assert setup_probe.closed == [77] and install_spy.scheduled == []


def test_other_nonzero_exit_code_reports_install_failure(monkeypatch, tmp_path, install_spy, setup_probe):
    monkeypatch.setattr(updater, "_launch_installer", lambda path: (None, 77))
    exe, quit_fn = _installer_in(tmp_path), MagicMock()
    assert updater._start_install(exe, MagicMock(), quit_fn) is True

    setup_probe.exit_code = 5
    _poll_once(install_spy)

    quit_fn.assert_not_called()
    assert len(install_spy.shown) == 1
    assert "exit code 5" in install_spy.shown[0][1]
    assert "administrator" not in install_spy.shown[0][1]
    assert not os.path.exists(exe)
    assert setup_probe.closed == [77]


def test_clean_exit_without_seeing_the_mutex_quits(monkeypatch, tmp_path, install_spy, setup_probe):
    monkeypatch.setattr(updater, "_launch_installer", lambda path: (None, 77))
    quit_fn = MagicMock()
    assert updater._start_install(_installer_in(tmp_path), MagicMock(), quit_fn) is True

    setup_probe.exit_code = 0
    _poll_once(install_spy)

    quit_fn.assert_called_once_with()
    assert setup_probe.closed == [77] and install_spy.shown == []


def _fake_kernel32(monkeypatch, open_result, last_error):
    import ctypes
    k32 = ctypes.windll.kernel32
    fakes = {"OpenMutexW": MagicMock(return_value=open_result),
             "CloseHandle": MagicMock(return_value=True),
             "GetLastError": MagicMock(return_value=last_error)}
    for name, fake in fakes.items():
        monkeypatch.setattr(k32, name, fake, raising=False)
    return fakes


def test_setup_mutex_seen_when_it_opens(monkeypatch):
    fakes = _fake_kernel32(monkeypatch, open_result=1234, last_error=0)
    assert updater._setup_mutex_seen() is True
    assert fakes["OpenMutexW"].call_args.args == (0x00100000, False, updater.SETUP_MUTEX)
    fakes["CloseHandle"].assert_called_once_with(1234)


def test_setup_mutex_access_denied_counts_as_seen(monkeypatch):
    _fake_kernel32(monkeypatch, open_result=None, last_error=5)
    assert updater._setup_mutex_seen() is True


def test_setup_mutex_not_found_is_not_seen(monkeypatch):
    _fake_kernel32(monkeypatch, open_result=None, last_error=2)
    assert updater._setup_mutex_seen() is False


def test_installer_mutex_name_matches_the_iss():
    iss = open(os.path.join(os.path.dirname(updater.__file__), "istari.iss"), encoding="utf-8").read()
    assert f"SetupMutex={updater.SETUP_MUTEX}" in iss


def test_launch_installer_starts_unelevated_and_keeps_the_process_handle(monkeypatch):
    import ctypes
    seen = {}

    def fake_shell_execute(ref):
        sei = ref._obj
        seen.update(verb=sei.lpVerb, mask=sei.fMask)
        sei.hProcess = 4321
        return True

    shell32 = ctypes.windll.shell32
    monkeypatch.setattr(shell32, "ShellExecuteExW", fake_shell_execute, raising=False)

    assert updater._launch_installer(r"C:\x\Istari_Setup.exe") == (None, 4321)
    assert seen["verb"] == "open"                  # never "runas": that defeats runasoriginaluser
    assert seen["mask"] & 0x40                     # SEE_MASK_NOCLOSEPROCESS


def test_launch_installer_reports_the_win32_error_when_shellexecute_fails(monkeypatch):
    import ctypes
    shell32 = ctypes.windll.shell32
    monkeypatch.setattr(shell32, "ShellExecuteExW", MagicMock(return_value=False), raising=False)
    monkeypatch.setattr(ctypes.windll.kernel32, "GetLastError", lambda: 1223, raising=False)

    assert updater._launch_installer(r"C:\x\Istari_Setup.exe") == (1223, None)


# ── UP-2 / UP-7 / UP-9: the checker always finishes and always says something ─

def _run_checker(qtbot, monkeypatch, fetch, cfg=None, manual=False):
    import cfg as cfg_mod
    monkeypatch.setattr(cfg_mod, "load_cfg", lambda: dict(cfg or {}))
    monkeypatch.setattr(updater, "_fetch_release", fetch)
    c = UpdateChecker("o", "r", manual=manual)
    got = []
    c.update_available.connect(lambda *a: got.append(("update", a)))
    c.no_update.connect(lambda: got.append(("none", ())))
    c.check_failed.connect(lambda msg: got.append(("failed", (msg,))))
    c.start()
    qtbot.waitUntil(lambda: not c._thread.isRunning(), timeout=5000)
    qtbot.wait(50)   # let queued signals land
    return got


@pytest.mark.parametrize("payload", [
    [],
    {"tag_name": None, "assets": []},
    {"tag_name": 5},
    "string",
])
def test_malformed_reply_ends_in_check_failed_and_stops_the_thread(qtbot, monkeypatch, payload):
    got = _run_checker(qtbot, monkeypatch, lambda o, r: (payload, ""))
    assert [g[0] for g in got] == ["failed"]


def test_assets_null_does_not_crash_the_checker(qtbot, monkeypatch):
    rel = {"tag_name": "v99.0.0", "assets": None}
    got = _run_checker(qtbot, monkeypatch, lambda o, r: (rel, ""))
    assert [g[0] for g in got] == ["none"]


def test_exception_inside_the_check_is_reported_not_swallowed(qtbot, monkeypatch):
    def boom(o, r):
        raise TypeError("boom")
    got = _run_checker(qtbot, monkeypatch, boom)
    assert [g[0] for g in got] == ["failed"]


def test_check_failed_still_works_with_a_slot_that_takes_no_argument(qtbot, monkeypatch):
    """istari.py connects no-argument slots to check_failed."""
    import cfg as cfg_mod
    monkeypatch.setattr(cfg_mod, "load_cfg", lambda: {})
    monkeypatch.setattr(updater, "_fetch_release", lambda o, r: (None, "network"))
    c = UpdateChecker("o", "r")
    hits = []
    c.check_failed.connect(lambda: hits.append(1))
    c.start()
    qtbot.waitUntil(lambda: bool(hits), timeout=5000)


RELEASE = {"tag_name": "v99.0.0", "body": "notes",
           "assets": [{"name": "Istari_Setup.exe", "browser_download_url": "https://x/Istari_Setup.exe"}]}


def test_manual_check_offers_a_skipped_version(qtbot, monkeypatch):
    got = _run_checker(qtbot, monkeypatch, lambda o, r: (RELEASE, ""),
                       cfg={"skipped_version": "v99.0.0"}, manual=True)
    assert [g[0] for g in got] == ["update"]


def test_background_check_still_honours_skip(qtbot, monkeypatch):
    got = _run_checker(qtbot, monkeypatch, lambda o, r: (RELEASE, ""),
                       cfg={"skipped_version": "v99.0.0"}, manual=False)
    assert [g[0] for g in got] == ["none"]


def _http_error(code):
    return urllib.error.HTTPError(url="", code=code, msg="x", hdrs=None, fp=None)


@pytest.mark.parametrize("code,reason", [(403, "rate_limit"), (429, "rate_limit"),
                                         (404, "not_found"), (500, "http")])
def test_http_errors_get_their_own_reason(code, reason):
    with patch("updater.urllib.request.urlopen", side_effect=_http_error(code)):
        assert updater._fetch_release("o", "r") == (None, reason)


def test_network_error_reason_and_texts_differ():
    with patch("updater.urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
        assert updater._fetch_release("o", "r") == (None, "network")
    assert "rate limit" in failure_text("rate_limit").lower()
    assert "connection" in failure_text("network").lower()
    assert failure_text("rate_limit") != failure_text("network")


def test_checker_passes_the_reason_text_to_check_failed(qtbot, monkeypatch):
    got = _run_checker(qtbot, monkeypatch, lambda o, r: (None, "rate_limit"))
    assert got == [("failed", (failure_text("rate_limit"),))]


# ── UP-8: strict version compare ──────────────────────────────────────────────

@pytest.mark.parametrize("remote,current,expected", [
    ("v1.0.24.0",     "1.0.24", False),   # four parts: no reinstall loop
    ("v1.0.25-rc1",   "1.0.25", False),   # release candidate is not newer than final
    ("v1.0.25-beta",  "1.0.24", False),   # pre-releases are never offered
    ("v1.0.24+build5", "1.0.24", False),
    ("2026.11.16",    "1.0.24", True),    # still a valid MAJOR.MINOR.PATCH
    ("latest",        "1.0.24", False),
    (None,            "1.0.24", False),
    ("v1.0.25",       "1.0.24", True),
    ("v1.0.10",       "1.0.9",  True),    # numeric, not lexical
])
def test_is_newer_strict(remote, current, expected):
    assert _is_newer(remote, current) is expected


# ── UP-11: the installer is picked by name ────────────────────────────────────

def test_installer_asset_is_picked_by_name_not_position():
    release = {"assets": [
        {"name": "other.exe",        "browser_download_url": "https://x/other.exe"},
        {"name": "Istari_Setup.exe", "browser_download_url": "https://x/Istari_Setup.exe"},
    ]}
    assert _find_installer_asset(release) == "https://x/Istari_Setup.exe"


def test_a_lone_foreign_exe_is_not_the_installer():
    assert _find_installer_asset(
        {"assets": [{"name": "other.exe", "browser_download_url": "https://x/other.exe"}]}) is None


# ── UP-6: corruption is not reported as a missing checksum ────────────────────

def test_hash_mismatch_message_is_not_the_missing_checksum_message():
    title, body = _friendly_error("SHA256 mismatch: expected a, got b")
    assert "does not publish" not in body
    assert "corrupt" in title.lower() or "corrupt" in body.lower()
    assert _friendly_error("No SHA256 checksum published for this release")[0] == \
        "Update Could Not Be Verified"


def test_tls_hostname_mismatch_is_still_a_secure_connection_error():
    assert _friendly_error("[SSL: CERTIFICATE_VERIFY_FAILED] Hostname mismatch")[0] == \
        "Secure Connection Failed"


# ── UP-4: timeouts, cleanup, cancel ───────────────────────────────────────────

class _Server:
    """Local HTTP server: /Istari_Setup.exe behaves per `mode`, .sha256 serves `digest`."""

    def __init__(self, mode, body=b"installer-bytes", digest=None):
        outer = self
        self.release = threading.Event()
        self.body = body
        self.digest = digest or hashlib.sha256(body).hexdigest()

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path.endswith(".sha256"):
                    data = (outer.digest + "  Istari_Setup.exe\n").encode()
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if mode == "stall":
                    self.send_response(200)
                    self.send_header("Content-Length", "1000000")
                    self.end_headers()
                    self.wfile.flush()
                    outer.release.wait(15)
                elif mode == "truncated":
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(outer.body) + 100))
                    self.end_headers()
                    self.wfile.write(outer.body)
                else:
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(outer.body)))
                    self.end_headers()
                    self.wfile.write(outer.body)

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/Istari_Setup.exe"

    def close(self):
        self.release.set()
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server(request, tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    made = []

    def make(mode, **kw):
        s = _Server(mode, **kw)
        made.append(s)
        return s
    yield make
    for s in made:
        s.close()


def test_stalled_download_times_out_and_leaves_no_temp_dir(server, tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "DOWNLOAD_TIMEOUT", 1)
    srv = server("stall")
    d, errors, finished = _stub_downloader(srv.url)

    t0 = time.monotonic()
    d._run()

    assert time.monotonic() - t0 < 8
    assert finished == [] and len(errors) == 1
    _assert_no_update_dirs(tmp_path)


def test_checksum_mismatch_deletes_the_bad_installer(server, tmp_path):
    srv = server("ok", digest="0" * 64)
    d, errors, finished = _stub_downloader(srv.url)

    d._run()

    assert finished == []
    assert len(errors) == 1 and "mismatch" in errors[0].lower()
    _assert_no_update_dirs(tmp_path)


def test_truncated_download_is_an_error_and_cleaned_up(server, tmp_path):
    srv = server("truncated")
    d, errors, finished = _stub_downloader(srv.url)

    d._run()

    assert finished == [] and len(errors) == 1
    _assert_no_update_dirs(tmp_path)


def test_verified_download_keeps_only_the_installer(server, tmp_path):
    srv = server("ok", body=b"good installer")
    d, errors, finished = _stub_downloader(srv.url)

    d._run()

    assert errors == [] and len(finished) == 1
    assert open(finished[0], "rb").read() == b"good installer"
    assert os.listdir(os.path.dirname(finished[0])) == ["Istari_Setup.exe"]   # no .part


def test_cancel_stops_the_download_and_cleans_up(server, tmp_path):
    srv = server("ok")
    d, errors, finished = _stub_downloader(srv.url)
    d.cancel()

    d._run()

    assert errors == [] and finished == []
    d.cancelled.emit.assert_called_once()
    _assert_no_update_dirs(tmp_path)


def test_missing_checksum_downloads_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    d, errors, _ = _stub_downloader()
    with patch("updater.urllib.request.urlopen", side_effect=_http_error(404)) as uo:
        d._run()
    assert len(errors) == 1
    assert uo.call_count == 1          # only the sidecar was requested
    _assert_no_update_dirs(tmp_path)


def test_stale_update_dirs_from_earlier_runs_are_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    old, fresh, other = (tmp_path / n for n in ("istari_update_old", "istari_update_new", "keepme"))
    for d in (old, fresh, other):
        d.mkdir()
        (d / "f").write_bytes(b"x")
    two_hours_ago = time.time() - 7200
    os.utime(old, (two_hours_ago, two_hours_ago))
    os.utime(other, (two_hours_ago, two_hours_ago))

    _cleanup_stale_update_dirs()

    assert not old.exists()
    assert fresh.exists()       # may still hold a running installer
    assert other.exists()       # not ours


# ── UP-10: release notes are rendered as markdown ─────────────────────────────

def test_release_notes_label_uses_markdown(qtbot):
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QLabel
    dlg = updater.UpdateDialog("v9.9.9", "## What's Changed\n* **fix** a thing")
    qtbot.addWidget(dlg)
    lbl = next(l for l in dlg.findChildren(QLabel) if l.objectName() == "notes_label")
    assert lbl.textFormat() == Qt.TextFormat.MarkdownText


def test_trim_notes_cuts_on_a_boundary():
    text = "word " * 200
    out = _trim_notes(text)
    assert out.endswith("…") and len(out) <= 321
    assert not out[:-1].endswith("wor")
    assert _trim_notes("short") == "short"


# ── OV-12: no ignored parent argument ─────────────────────────────────────────
def test_update_checker_has_no_ignored_parent_argument():
    import inspect
    # A parented QObject cannot be moved to the worker thread, so the checker
    # is parentless and callers keep their own reference.
    assert "parent" not in inspect.signature(UpdateChecker.__init__).parameters
    assert UpdateChecker("o", "r").parent() is None


# -- R-UP-1 / R-UP-3 -----------------------------------------------------------

def _real_progress(qtbot):
    prog = updater.DownloadProgressDialog()
    qtbot.addWidget(prog)
    prog.show()
    assert prog.isVisible()
    return prog


def test_rup1_failed_launch_hides_the_real_progress_dialog(qtbot, monkeypatch, tmp_path, install_spy):
    monkeypatch.setattr(updater, "_launch_installer", lambda path: (5, None))
    prog = _real_progress(qtbot)
    assert updater._start_install(_installer_in(tmp_path), prog, MagicMock()) is False
    assert not prog.isVisible()


@pytest.mark.parametrize("signal_name", ["error", "cancelled"])
def test_rup1_cancel_and_error_hide_the_progress_dialog(qtbot, monkeypatch, signal_name):
    from PyQt6.QtCore import QObject, pyqtSignal

    holder = {}

    class FakeDl(QObject):
        progress = pyqtSignal(int)
        finished = pyqtSignal(str)
        error = pyqtSignal(str)
        cancelled = pyqtSignal()

        def __init__(self, url):
            super().__init__()
            holder["dl"] = self

        def cancel(self): pass
        def start(self): pass

    class FakeUpdate:
        UPDATE, SKIP = 1, 2
        def __init__(self, *a, **k): pass
        def adjustSize(self): pass
        def _center_on_screen(self): pass
        def exec(self): pass
        def choice(self): return 1

    shown = []
    monkeypatch.setattr(updater, "UpdateDialog", FakeUpdate)
    monkeypatch.setattr(updater, "InstallerDownloader", FakeDl)
    monkeypatch.setattr(updater, "_show_download_error", lambda raw, parent=None: shown.append(raw))
    created = []
    real_cls = updater.DownloadProgressDialog

    def make_prog(*a, **k):
        p = real_cls(*a, **k)
        qtbot.addWidget(p)
        created.append(p)
        return p
    monkeypatch.setattr(updater, "DownloadProgressDialog", make_prog)

    updater.prompt_and_install("v9.9.9", "https://x/Istari_Setup.exe")
    prog = created[0]
    assert prog.isVisible()
    if signal_name == "error":
        holder["dl"].error.emit("boom")
    else:
        prog.reject()                     # Esc asks to cancel; it must not hide by itself
        holder["dl"].cancelled.emit()
    assert not prog.isVisible()


def test_rup3_cancel_after_the_last_chunk_never_runs_the_installer(server, tmp_path):
    srv = server("ok")
    d, errors, finished = _stub_downloader(srv.url)
    real = d._download

    def download_then_cancel(dest):
        ok = real(dest)
        d.cancel()                         # Cancel lands after the final chunk
        return ok
    d._download = download_then_cancel

    d._run()

    assert finished == [] and errors == []
    d.cancelled.emit.assert_called_once()
    _assert_no_update_dirs(tmp_path)
