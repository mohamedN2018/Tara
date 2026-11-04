"""Gunicorn logger that keeps playback tokens out of the access log (roadmap 5.3).

HLS playlist URLs carry the viewer's playback token in the query string, so
their requests are not written to the access log at all. Everything else is
logged as usual.
"""

from __future__ import annotations

from gunicorn.glogging import Logger as _Logger

# Matches media_app.urls: /api/v1/media/<id>/hls/<name>.m3u8
SILENT_PATH_PART = "/hls/"


class Logger(_Logger):
    def access(self, resp, req, environ, request_time):
        if SILENT_PATH_PART in (environ.get("PATH_INFO") or ""):
            return
        super().access(resp, req, environ, request_time)
