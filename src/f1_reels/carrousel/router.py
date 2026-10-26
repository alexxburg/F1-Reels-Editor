"""Carrousel HTTP layer — job board browsing and PNG rendering."""

import io
import zipfile

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, Response

from .db import AWS_REGION, DSQL_HOST, DSQL_USER, TokenError, query_db
from .render import render_single

router = APIRouter(prefix="/api/carrousel", tags=["carrousel"])


def _token_error_response(e):
    return JSONResponse(
        status_code=500,
        content={
            "error": (
                "Missing/invalid AWS credentials for DSQL IAM auth. "
                "Requires AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY "
                "(or IAM role / SSO session), plus "
                f"AWS_REGION={AWS_REGION}, DSQL_HOST={DSQL_HOST}, "
                f"DSQL_USER={DSQL_USER}. Details: {e}"
            )
        },
    )


def _db_error_response(e):
    msg = str(e)
    if "Unable to locate credentials" in msg or "NoCredentials" in msg:
        return _token_error_response(e)
    return JSONResponse(status_code=500, content={"error": f"database error: {e}"})


@router.get("/jobs")
def list_jobs(
    search: str = Query(default=""),
    team: str = Query(default=""),
    location: str = Query(default=""),
    job_type: str = Query(default="", alias="type"),
):
    search = (search or "").strip()
    team = (team or "").strip()
    location = (location or "").strip()
    job_type = (job_type or "").strip()

    sql = (
        "SELECT job_id, job_title, job_team, job_subteam, job_type, "
        "job_location, job_link FROM public.jobs WHERE relevancy='live'"
    )
    params = []
    if search:
        sql += " AND (job_title ILIKE %s OR job_description ILIKE %s OR job_link ILIKE %s)"
        like = f"%{search}%"
        params.extend([like, like, like])
    if team:
        sql += " AND job_team = %s"
        params.append(team)
    if location:
        sql += " AND job_location = %s"
        params.append(location)
    if job_type:
        sql += " AND job_type = %s"
        params.append(job_type)
    sql += " ORDER BY last_seen DESC LIMIT 500"

    try:
        rows = query_db(sql, params)
    except TokenError as e:
        return _token_error_response(e)
    except Exception as e:
        return _db_error_response(e)

    return [
        {
            "job_id": r[0],
            "title": r[1],
            "team": r[2],
            "subteam": r[3],
            "type": r[4],
            "location": r[5],
            "link": r[6],
        }
        for r in rows
    ]


@router.get("/filters")
def list_filters():
    try:
        teams = query_db(
            "SELECT DISTINCT job_team FROM public.jobs "
            "WHERE relevancy='live' AND job_team IS NOT NULL ORDER BY 1"
        )
        locations = query_db(
            "SELECT DISTINCT job_location FROM public.jobs "
            "WHERE relevancy='live' AND job_location IS NOT NULL ORDER BY 1"
        )
        types = query_db(
            "SELECT DISTINCT job_type FROM public.jobs "
            "WHERE relevancy='live' AND job_type IS NOT NULL ORDER BY 1"
        )
    except TokenError as e:
        return _token_error_response(e)
    except Exception as e:
        return _db_error_response(e)
    return {
        "teams": [r[0] for r in teams],
        "locations": [r[0] for r in locations],
        "types": [r[0] for r in types],
    }


def _live_by_id(ids):
    placeholders = ",".join(["%s"] * len(ids))
    sql = (
        "SELECT job_id, job_title, job_team, job_subteam, job_type, "
        f"job_location, job_link FROM public.jobs WHERE relevancy='live' AND job_id IN ({placeholders})"
    )
    return query_db(sql, ids)


@router.post("/image")
def request_images(payload: dict):
    ids = payload.get("ids") if isinstance(payload, dict) else None
    if not isinstance(ids, list) or len(ids) < 1 or len(ids) > 24:
        return JSONResponse(
            status_code=400, content={"error": "ids must be a list of 1..24 job ids"}
        )
    clean = []
    for i in ids:
        if isinstance(i, bool) or not isinstance(i, int):
            return JSONResponse(
                status_code=400, content={"error": "ids must be integers"}
            )
        clean.append(i)
    ids = clean

    try:
        rows = _live_by_id(ids)
    except TokenError as e:
        return _token_error_response(e)
    except Exception as e:
        return _db_error_response(e)

    if not rows:
        return JSONResponse(
            status_code=404, content={"error": "no live jobs found for given ids"}
        )

    by_id = {r[0]: r for r in rows}
    seen = set()
    images = []
    for jid in ids:
        if jid in by_id and jid not in seen:
            seen.add(jid)
            images.append({"job_id": jid, "url": f"/api/carrousel/image/{jid}"})
    if not images:
        return JSONResponse(
            status_code=404, content={"error": "no live jobs found for given ids"}
        )
    return {"images": images}


@router.get("/image/{job_id}")
def get_image(job_id: int):
    sql = (
        "SELECT job_id, job_title, job_team, job_subteam, job_type, "
        "job_location, job_link FROM public.jobs "
        "WHERE relevancy='live' AND job_id = %s"
    )
    try:
        rows = query_db(sql, [job_id])
    except TokenError as e:
        return _token_error_response(e)
    except Exception as e:
        return _db_error_response(e)

    if not rows:
        return JSONResponse(status_code=404, content={"error": "job not found"})

    img = render_single(rows[0])
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Response(content=buf.getvalue(), media_type="image/png")


@router.get("/images.zip")
def get_images_zip(ids: str = Query(default="")):
    raw = (ids or "").strip()
    if not raw:
        return JSONResponse(
            status_code=400,
            content={"error": "ids query param required, e.g. ?ids=1,2,3"},
        )
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) < 1 or len(parts) > 24 or any(p == "" for p in parts):
        return JSONResponse(
            status_code=400,
            content={"error": "ids must be 1..24 comma-separated job ids"},
        )
    try:
        id_list = [int(p) for p in parts]
    except (TypeError, ValueError):
        return JSONResponse(
            status_code=400, content={"error": "ids must be integers"}
        )

    placeholders = ",".join(["%s"] * len(id_list))
    sql = (
        "SELECT job_id, job_title, job_team, job_subteam, job_type, "
        f"job_location, job_link FROM public.jobs WHERE relevancy='live' AND job_id IN ({placeholders})"
    )
    try:
        rows = query_db(sql, id_list)
    except TokenError as e:
        return _token_error_response(e)
    except Exception as e:
        return _db_error_response(e)

    if not rows:
        return JSONResponse(
            status_code=404, content={"error": "no live jobs found for given ids"}
        )

    by_id = {r[0]: r for r in rows}
    ordered = []
    seen = set()
    for jid in id_list:
        if jid in by_id and jid not in seen:
            seen.add(jid)
            ordered.append(by_id[jid])

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for row in ordered:
            img = render_single(row)
            png_buf = io.BytesIO()
            img.save(png_buf, format="PNG")
            zf.writestr(f"{row[0]}.png", png_buf.getvalue())
    zip_buf.seek(0)
    return Response(
        content=zip_buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=carrousel.zip"},
    )
