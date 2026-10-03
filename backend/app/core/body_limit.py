"""Refuse requests whose body is too large, before it is stored anywhere."""

import json


from starlette.exceptions import HTTPException


class _BodyTooLarge(HTTPException):
    """Raised while the body is being read. As an HTTP error it is turned
    into a 413 answer wherever in the app the reading happens."""


class BodySizeLimitMiddleware:
    """Stops reading a request as soon as it passes the size limit.

    Without this, an upload is first received in full and only then
    measured, so a huge upload could fill the disk.
    """

    def __init__(self, app, max_bytes: int, detail: str):
        self.app = app
        self.max_bytes = max_bytes
        self.detail = detail

    async def _reject(self, send) -> None:
        body = json.dumps({"detail": self.detail}).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"connection", b"close"),
            ],
        })
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # The size the client announces, when it announces one.
        for name, value in scope.get("headers", []):
            if name == b"content-length" and value.isdigit():
                if int(value) > self.max_bytes:
                    await self._reject(send)
                    return

        received = 0
        response_started = False

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _BodyTooLarge(status_code=413, detail=self.detail)
            return message

        async def tracking_send(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            if response_started:
                raise
            await self._reject(send)
