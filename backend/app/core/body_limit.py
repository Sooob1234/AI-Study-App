"""Refuse requests whose body is too large, before it is stored anywhere."""

import json
from typing import Callable

from starlette.exceptions import HTTPException


class _BodyTooLarge(HTTPException):
    """Raised while the body is being read. As an HTTP error it is turned
    into a 413 answer wherever in the app the reading happens."""


class BodySizeLimitMiddleware:
    """Stops reading a request as soon as it passes its size limit.

    Without this, an upload is first received in full and only then
    measured, so a huge upload could fill the disk.

    `limit_for` receives the request path and returns the largest body, in
    bytes, that this path may receive.
    """

    def __init__(
        self,
        app,
        limit_for: Callable[[str], int],
        refuse_before_reading: Callable | None = None,
    ):
        self.app = app
        self.limit_for = limit_for
        # Optional: given the request, returns (status, message) to refuse
        # it before its body is read, or None to let it through.
        self.refuse_before_reading = refuse_before_reading

    @staticmethod
    def _detail(max_bytes: int) -> str:
        megabytes = max(1, max_bytes // (1024 * 1024))
        return f"Request is larger than {megabytes} MB"

    async def _reject(self, send, max_bytes: int) -> None:
        await self._answer(send, 413, self._detail(max_bytes))

    @staticmethod
    async def _answer(send, status: int, detail: str) -> None:
        body = json.dumps({"detail": detail}).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": status,
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

        if self.refuse_before_reading is not None:
            refusal = self.refuse_before_reading(scope)
            if refusal is not None:
                await self._answer(send, *refusal)
                return

        max_bytes = self.limit_for(scope.get("path", ""))

        # The size the client announces, when it announces one.
        for name, value in scope.get("headers", []):
            if name == b"content-length" and value.isdigit():
                if int(value) > max_bytes:
                    await self._reject(send, max_bytes)
                    return

        received = 0
        response_started = False

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > max_bytes:
                    raise _BodyTooLarge(
                        status_code=413, detail=self._detail(max_bytes)
                    )
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
            await self._reject(send, max_bytes)
