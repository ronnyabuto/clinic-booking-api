from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from clinic.config import Settings
from clinic.database import make_engine, make_session_factory
from clinic.errors import BookingError
from clinic.routes import router
from clinic.service import BookingService


def _invalid_json_response(details: list[dict]) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "error": {
                "code": "invalid_json",
                "message": "Request body is not valid JSON",
                "details": details,
            }
        },
    )


def create_app(service: BookingService | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        if service is None:
            engine = make_engine(Settings().database_url)
            app.state.booking_service = BookingService(make_session_factory(engine))
            try:
                yield
            finally:
                engine.dispose()
        else:
            app.state.booking_service = service
            yield

    app = FastAPI(title="Clinic Booking API", version="0.1.0", lifespan=lifespan)
    app.include_router(router)

    @app.exception_handler(BookingError)
    async def booking_error(request: Request, error: BookingError):
        headers = {"Retry-After": "1"} if error.status == 503 else None
        return JSONResponse(
            status_code=error.status,
            content={"error": {"code": error.code, "message": error.message}},
            headers=headers,
        )

    @app.exception_handler(400)
    async def bad_request(request: Request, error: HTTPException):
        if isinstance(error.__cause__, UnicodeDecodeError):
            return _invalid_json_response(
                [
                    {
                        "location": ["body"],
                        "message": "JSON body could not be decoded",
                        "type": "json_invalid",
                    }
                ]
            )
        return await http_exception_handler(request, error)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        details = [
            {"location": list(item["loc"]), "message": item["msg"], "type": item["type"]}
            for item in error.errors()
        ]
        if any(item["type"] == "json_invalid" for item in details):
            return _invalid_json_response(details)
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_request",
                    "message": "Request validation failed",
                    "details": details,
                }
            },
        )

    return app


app = create_app()
