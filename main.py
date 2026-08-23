"""
Slyp API — FastAPI wrapper around the slyp pipeline.

One real endpoint: POST /analyse. GET /health only proves the process is
alive. Resist adding a second real endpoint.

Request path, in this exact order:

    accept upload
        -> enforce PDF by magic bytes (not extension or content-type)
        -> enforce max file size, rejecting early
        -> extract_payslip()   (read -> redact -> allowlist filter ->
                                 fail-closed gate -> model call)
        -> analyse_payslip()   (the calculation engine + findings layer)
        -> response

In-memory only. No temp files, ever - see the spool_max_size patch
below, which closes a real gap: Starlette's default multipart parser
spills to an actual temp file on disk for any part over 1MB, which would
silently violate "the document is never persisted" for a normal
multi-page payslip PDF. Patching it to MAX_UPLOAD_BYTES guarantees any
upload under our own size limit never touches disk, without giving up on
using standard multipart/form-data for the upload.

Logging: request timing and error TYPE NAMES only. Never the extracted
text, field values, findings, or the pound figure - and never str(exc)
either, since a pydantic ValidationError's message can itself contain
real field values. Every logging call on this path is audited against
that rule; if you add one, keep it to type(exc).__name__ and timing.
"""

from __future__ import annotations

# Must run before any `slyp.*` import: slyp.extraction reads
# SLYP_EXTRACTION_MODEL from the environment at MODULE IMPORT TIME (it's a
# top-level constant, not read inside a function), so if dotenv loads
# after that import has already run, .env's value is silently ignored in
# favour of the hardcoded fallback - which is exactly what happened
# during development here (the fallback model ID isn't a valid one to
# call, so every request failed with a 400 from the Anthropic API and no
# obvious cause in the code that raised it).
from dotenv import load_dotenv

load_dotenv()  # local dev only - matches tools/try_extraction.py's convention.
# In production, ANTHROPIC_API_KEY (and SLYP_EXTRACTION_MODEL, if set)
# come from platform environment config (Phase 10), not from a .env file
# that would need to be deployed.

import logging
import os
import time

import starlette.formparsers as _formparsers
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pdfminer.pdfdocument import PDFEncryptionError, PDFPasswordIncorrect
from pdfminer.pdfparser import PDFSyntaxError
from pdfplumber.utils.exceptions import PdfminerException

from slyp.analysis import analyse_payslip
from slyp.contract import AnalysisResult, UserContext
from slyp.extraction import (
    NotAPayslip,
    RedactionFailure,
    UnreadableDocument,
    extract_payslip,
    required_credential_name,
)

logger = logging.getLogger("slyp.api")
logging.basicConfig(level=logging.INFO)


# ==========================================================================
# Startup configuration check
# ==========================================================================
#
# Refuse to boot rather than boot healthy and die on the first upload.
#
# The failure this prevents, seen during verification: with
# SLYP_MODEL_PROVIDER unset, the provider silently defaults to
# "anthropic", anthropic.Anthropic() constructs happily with no API key at
# all, the process starts, /health returns 200 - and the first real upload
# comes back as a generic 500. On a deployed instance that is
# indistinguishable from a healthy server until someone tries it, which on
# a demo day means finding out on stage.
#
# Deliberately here and not in slyp/extraction.py: that module is imported
# by the test suite, which has no business holding a real API key. Nothing
# imports main.py except the server.

_CREDENTIAL_VAR = required_credential_name()

if not os.environ.get(_CREDENTIAL_VAR, "").strip():
    raise RuntimeError(
        f"{_CREDENTIAL_VAR} is not set. The extraction provider is "
        f"'{os.environ.get('SLYP_MODEL_PROVIDER', 'anthropic')}', which needs "
        f"that variable. Set it in the platform's environment config (or in "
        f".env for local development) and start again. Refusing to start "
        f"rather than accept uploads this process cannot actually analyse."
    )

# Not a hard failure - localhost is the correct value in local development,
# and there is no reliable way to tell a real deployment from a laptop
# without inventing another variable to get wrong. Logged loudly instead,
# because a CORS list still pointing at localhost on a deployed instance
# blocks every browser request and surfaces in the UI as "Couldn't reach
# the server" - which reads exactly like a dead backend.
if os.environ.get("SLYP_CORS_ORIGINS") is None:
    logger.warning(
        "SLYP_CORS_ORIGINS is not set; allowing only http://localhost:3000. "
        "If this is a deployed instance, set it to the frontend's real "
        "origin or every browser request will be blocked."
    )

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB - generous for a payslip PDF
_PDF_MAGIC = b"%PDF-"

# See the module docstring: without this, any upload part over 1MB spills
# to a real temp file regardless of what we pass request.form() below.
_formparsers.MultiPartParser.spool_max_size = MAX_UPLOAD_BYTES

CORS_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "SLYP_CORS_ORIGINS", "http://localhost:3000"
    ).split(",")
    if origin.strip()
]

app = FastAPI(title="Slyp API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    allow_credentials=False,
)


# ==========================================================================
# Error responses
# ==========================================================================
#
# Every error the client can see is a plain-English message with no
# stack trace and no extracted content, per item 43. `status` mirrors
# AnalysisResult.status where it makes sense so the frontend can use one
# switch statement for both "the analysis ran but found a problem" and
# "the request itself couldn't be processed".


def _clean_error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": message})


@app.exception_handler(RequestValidationError)
async def _on_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # FastAPI's default handler echoes the submitted value back in the
    # response body, which could include payslip content depending on
    # what failed to validate. Replace it with a generic message.
    return _clean_error(400, "The request could not be understood. Please try again.")


@app.exception_handler(Exception)
async def _on_unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    # Last-resort backstop so nothing - not even a bug we didn't
    # anticipate - reaches the client as a raw traceback.
    logger.error("unhandled exception: %s", type(exc).__name__)
    return _clean_error(500, "Something went wrong. Please try again.")


# ==========================================================================
# Health
# ==========================================================================


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# ==========================================================================
# Analyse
# ==========================================================================


@app.post("/analyse", response_model=AnalysisResult)
async def analyse(request: Request) -> AnalysisResult:
    started = time.monotonic()

    def _elapsed() -> float:
        return time.monotonic() - started

    # Reject an obviously oversized request before Starlette parses any
    # of it, using the client-supplied Content-Length as a fast
    # pre-check. This is a hint, not a guarantee (a client can lie about
    # it) - the real enforcement is max_part_size below, which Starlette
    # checks as it streams the body in, not after buffering it whole.
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > MAX_UPLOAD_BYTES:
                logger.info("analyse rejected: oversized (content-length) in %.3fs", _elapsed())
                return _clean_error(
                    413,
                    f"That file is too large. Please upload a PDF under "
                    f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
                )
        except ValueError:
            pass

    try:
        form = await request.form(max_part_size=MAX_UPLOAD_BYTES)
    except _formparsers.MultiPartException:
        logger.info("analyse rejected: oversized (part size) in %.3fs", _elapsed())
        return _clean_error(
            413,
            f"That file is too large. Please upload a PDF under "
            f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        )

    upload = form.get("file")
    if upload is None or not hasattr(upload, "read"):
        logger.info("analyse rejected: no file field in %.3fs", _elapsed())
        return _clean_error(400, "No file was uploaded. Please choose a payslip PDF.")

    pdf_bytes = await upload.read()

    if not pdf_bytes:
        logger.info("analyse rejected: empty file in %.3fs", _elapsed())
        return _clean_error(400, "The uploaded file is empty. Please choose a payslip PDF.")

    if len(pdf_bytes) > MAX_UPLOAD_BYTES:
        logger.info("analyse rejected: oversized (actual size) in %.3fs", _elapsed())
        return _clean_error(
            413,
            f"That file is too large. Please upload a PDF under "
            f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        )

    if not pdf_bytes.startswith(_PDF_MAGIC):
        logger.info("analyse rejected: not a PDF (magic bytes) in %.3fs", _elapsed())
        return _clean_error(400, "That doesn't look like a PDF. Please upload a payslip PDF.")

    only_job_raw = form.get("only_job")
    only_job = {"true": True, "false": False}.get(
        only_job_raw.lower() if isinstance(only_job_raw, str) else None
    )
    user_context = UserContext(only_job=only_job)

    filename = getattr(upload, "filename", None)

    try:
        extract = extract_payslip(pdf_bytes, filename=filename)
        result = analyse_payslip(extract, user_context)

    except PdfminerException as exc:
        # pdfplumber wraps every failure from opening the document -
        # including PDFPasswordIncorrect/PDFEncryptionError and
        # PDFSyntaxError - in this one exception type (see
        # pdfplumber.pdf.PDF.__init__: `except Exception as e: raise
        # PdfminerException(e)`). Unwrap one level to recover the
        # distinction for a clearer message.
        inner = exc.args[0] if exc.args else None
        if isinstance(inner, (PDFPasswordIncorrect, PDFEncryptionError)):
            logger.info("analyse failed: password-protected PDF in %.3fs", _elapsed())
            return _clean_error(
                422,
                "This PDF is password-protected. Please remove the "
                "password and try again.",
            )
        logger.info("analyse failed: corrupt/malformed PDF in %.3fs", _elapsed())
        return _clean_error(
            422,
            "This file couldn't be read as a PDF. It may be corrupted - "
            "please try a different file.",
        )

    except PDFSyntaxError:
        # Not wrapped in PdfminerException when it happens here: this is
        # per-page text extraction, after pdfplumber.open() already
        # succeeded, so a page with a broken content stream can still
        # raise the raw pdfminer error directly.
        logger.info("analyse failed: corrupt PDF (page content) in %.3fs", _elapsed())
        return _clean_error(
            422,
            "This file couldn't be read as a PDF. It may be corrupted - "
            "please try a different file.",
        )

    except UnreadableDocument:
        logger.info("analyse failed: no text layer in %.3fs", _elapsed())
        return _clean_error(
            422,
            "We couldn't read any text from this PDF. If it's a scanned "
            "image, try a version with selectable text, or enter the "
            "details manually.",
        )

    except NotAPayslip:
        logger.info("analyse failed: not recognised as a payslip in %.3fs", _elapsed())
        return _clean_error(
            422,
            "We couldn't recognise this document as a payslip. Please "
            "check the file and try again.",
        )

    except RedactionFailure as exc:
        # Fails closed: this exception means the payload was never sent
        # anywhere. The client just sees a refusal, never why - but the
        # exception message itself is safe to log: assert_safe_to_send
        # deliberately never includes the matched text, only which
        # pattern/check fired (e.g. "sort code", "unexplained run of
        # digits"), so logging it doesn't leak anything and turns the
        # next gate refusal into something diagnosable.
        logger.warning(
            "analyse refused by the redaction gate in %.3fs: %s", _elapsed(), exc
        )
        return _clean_error(
            422,
            "We couldn't safely process this document. Please try a "
            "different file or enter the details manually.",
        )

    except Exception as exc:
        logger.error("analyse failed unexpectedly: %s in %.3fs", type(exc).__name__, _elapsed())
        return _clean_error(
            500,
            "Something went wrong while analysing this payslip. Please "
            "try again.",
        )

    logger.info("analyse ok in %.3fs", _elapsed())
    return result
