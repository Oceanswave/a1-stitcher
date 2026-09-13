import json
import queue
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from a1_stitcher.player import page, serve, sidecar_paths
from a1_stitcher.storage import digest


def test_player_escapes_embedded_json_and_media_url():
    result = page(
        'a "<clip>.mp4', {"samples": [{"text": "</script><script>alert(1)</script>"}]}
    ).decode()
    assert '"text":"</script>' not in result
    assert "\\u003c/script>" in result
    assert "a%20%22%3Cclip%3E.mp4" in result


@pytest.mark.integration
def test_local_viewer_byte_ranges_allowlist_and_integrity(tmp_path, monkeypatch):
    video = tmp_path / "a clip.mp4"
    video.write_bytes(bytes(range(256)) * 8)
    sidecars = sidecar_paths(video)
    sidecars[0].write_text("{}")
    sidecars[1].write_bytes(b"<!doctype html><title>review</title>")
    receipt = tmp_path / (video.name + ".receipt.json")
    receipt.write_text(
        json.dumps(
            dict(output_sha256=digest(video), viewport_files={p.name: digest(p) for p in sidecars})
        )
    )
    created = queue.Queue()

    class Server(ThreadingHTTPServer):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created.put(self)

    monkeypatch.setattr("http.server.ThreadingHTTPServer", Server)
    errors = []

    def run():
        try:
            serve(video, port=0)
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        server = created.get(timeout=2)
    except queue.Empty:
        worker.join(timeout=1)
        if errors and isinstance(errors[0], PermissionError):
            pytest.skip("Loopback listener unavailable in this sandbox")
        raise AssertionError(errors)
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(url + "/", timeout=2) as r:
            assert r.read() == sidecars[1].read_bytes()
        with urlopen(
            Request(url + "/a%20clip.mp4", headers={"Range": "bytes=10-19"}), timeout=2
        ) as r:
            assert r.status == 206 and r.read() == bytes(range(10, 20))
            assert r.headers["Content-Range"] == "bytes 10-19/2048"
        with urlopen(
            Request(url + "/a%20clip.mp4", headers={"Range": "bytes=-3"}, method="HEAD"), timeout=2
        ) as r:
            assert r.status == 206 and r.headers["Content-Length"] == "3" and r.read() == b""
        for path in ["/../a%20clip.mp4.receipt.json", "/a%20clip.mp4.receipt.json", "/secret"]:
            with pytest.raises(HTTPError) as exc:
                urlopen(url + path, timeout=2)
            assert exc.value.code == 404
        with pytest.raises(HTTPError) as exc:
            urlopen(Request(url + "/a%20clip.mp4", headers={"Range": "bytes=4000-"}), timeout=2)
        assert exc.value.code == 416
    finally:
        server.shutdown()
        worker.join(timeout=2)
    sidecars[0].write_text("changed")
    with pytest.raises(Exception, match="sidecar"):
        serve(video, port=0)
