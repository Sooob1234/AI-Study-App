"""A single test page for trying the app by hand.

It is not the product's interface (that will be the mobile app). It only
lets the owner add a PDF, an audio file or a YouTube video and look at
what the processing produced, without using Swagger.
"""

import os

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter(include_in_schema=False)

_PAGE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "static",
    "prototype.html",
)


@router.get("/prototype")
def prototype_page():
    return FileResponse(
        _PAGE,
        media_type="text/html; charset=utf-8",
        # Always the newest version after an update.
        headers={"Cache-Control": "no-store"},
    )
