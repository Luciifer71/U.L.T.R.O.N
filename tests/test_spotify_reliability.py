"""Regression tests for Spotify HTTP responses and automatic launch."""


import pytest

from ultron.control import spotify_api as api


def test_playback_http_200_non_json_body_is_accepted(monkeypatch):
    import requests

    class Response:
        status_code = 200
        content = b"Playback request acknowledged"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def json(self):
            raise ValueError("Not JSON")

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def request(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(requests, "Session", Session)

    status, body = api._request(
        "PUT",
        "https://api.spotify.com/v1/me/player/pause",
        token="test-token",
    )

    assert status == 200
    assert body == {}


def test_auto_launch_waits_until_device_appears(monkeypatch):
    launches = []
    sleeps = []

    with monkeypatch.context() as patch:
        patch.setattr(api.sys, "platform", "win32")
        patch.setattr(
            api.subprocess,
            "Popen",
            lambda *args, **kwargs: launches.append(args) or object(),
        )

        client = api.SpotifyClient(sleep=sleeps.append)

        attempts = iter([
            None,
            None,
            {"id": "laptop", "name": "Laptop"},
        ])

        def device():
            value = next(attempts)
            if value is None:
                raise api.SpotifyError("Spotify reports no available playback devices.")
            return value

        patch.setattr(client, "device", device)

        result = client.device_for_playback()

    assert result["id"] == "laptop"
    assert len(launches) == 1
    assert sleeps == [1, 1]


def test_auto_launch_timeout_is_reported(monkeypatch):
    launches = []

    with monkeypatch.context() as patch:
        patch.setattr(api.sys, "platform", "win32")
        patch.setattr(
            api.subprocess,
            "Popen",
            lambda *args, **kwargs: launches.append(args) or object(),
        )

        client = api.SpotifyClient(sleep=lambda _: None)

        def no_device():
            raise api.SpotifyError("Spotify reports no available playback devices.")

        patch.setattr(client, "device", no_device)

        with pytest.raises(api.SpotifyError, match="within 15 seconds"):
            client.device_for_playback()

    assert len(launches) == 1
