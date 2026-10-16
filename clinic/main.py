from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from clinic.config import Settings
from clinic.database import make_engine, make_session_factory
from clinic.errors import BookingError
from clinic.routes import router
from clinic.service import BookingService


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

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        details = [
            {"location": list(item["loc"]), "message": item["msg"], "type": item["type"]}
            for item in error.errors()
        ]
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
