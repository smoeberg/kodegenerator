"""Human-facing error and recovery copy for the canonical DOR GUI.

This module only translates transport/domain feedback for presentation. It never
changes authority, retries mutations automatically, or interprets permissions as
granted.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import streamlit as st

from dashboard.api_client import DORAPIError


@dataclass(frozen=True)
class UserFacingAPIError:
    title: str
    message: str
    next_step: str
    can_reauthenticate: bool = False
    can_refresh: bool = False


def _payload_text(payload: Any) -> str:
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str):
            return detail
        if isinstance(detail, list):
            return " ".join(str(item) for item in detail)
    return str(payload or "")


def _validation_fields(payload: Any) -> tuple[str, ...]:
    if not isinstance(payload, dict) or not isinstance(payload.get("detail"), list):
        return ()
    fields: list[str] = []
    for item in payload["detail"]:
        if not isinstance(item, dict):
            continue
        loc = item.get("loc")
        if not isinstance(loc, (list, tuple)):
            continue
        parts = [str(part) for part in loc if str(part) not in {"body", "query", "path"}]
        if parts:
            fields.append(".".join(parts))
    return tuple(dict.fromkeys(fields))


def explain_api_error(exc: DORAPIError) -> UserFacingAPIError:
    """Translate a backend error into recovery-oriented operator language."""
    text = f"{exc} {_payload_text(exc.payload)}".casefold()

    if exc.status_code == 401:
        return UserFacingAPIError(
            title="Din session er udløbet",
            message="DOR kunne ikke bekræfte din session, så handlingen blev ikke gennemført.",
            next_step="Log ind igen og fortsæt fra den aktuelle sag.",
            can_reauthenticate=True,
        )

    if exc.status_code == 403 or any(
        marker in text
        for marker in ("authority deny", "authority denied", "forbidden", "permission denied")
    ):
        return UserFacingAPIError(
            title="Du har ikke adgang til denne handling",
            message="DOR har afvist handlingen, fordi din aktuelle rolle eller authority ikke tillader den.",
            next_step="Kontakt en administrator, hvis du mener, at du skal have denne rettighed.",
        )

    if any(marker in text for marker in ("fingerprint", "stale", "changed since", "version mismatch")):
        return UserFacingAPIError(
            title="Sagen er ændret siden du åbnede den",
            message="DOR bruger den aktuelle backend-version og gennemfører ikke en handling på et forældet grundlag.",
            next_step="Hent den aktuelle version af sagen og prøv igen.",
            can_refresh=True,
        )

    if any(
        marker in text
        for marker in (
            "budget",
            "max_files",
            "max files",
            "max_changed_lines",
            "changed-line",
            "changed line",
            "exceeds the approved",
            "scope is too large",
            "scope too large",
        )
    ):
        return UserFacingAPIError(
            title="Omfanget er for stort",
            message="Det valgte scope overstiger den grænse, som backend har godkendt for denne handling.",
            next_step="Reducer scope eller ændringsmængden og prøv igen. GUI'en ændrer ikke governance-budgettet.",
        )

    if exc.status_code == 422:
        fields = _validation_fields(exc.payload)
        field_copy = f" Kontrollér især: {', '.join(fields)}." if fields else ""
        return UserFacingAPIError(
            title="Oplysningerne er ikke gyldige",
            message="DOR kunne ikke validere de indsendte oplysninger." + field_copy,
            next_step="Ret de relevante felter og prøv igen.",
        )

    if exc.status_code == 404:
        return UserFacingAPIError(
            title="Det valgte element findes ikke længere",
            message="Det kan være blevet ændret eller erstattet, siden siden blev åbnet.",
            next_step="Hent den aktuelle visning og vælg elementet igen.",
            can_refresh=True,
        )

    if exc.status_code == 409:
        return UserFacingAPIError(
            title="Handlingen passer ikke længere til den aktuelle situation",
            message="Backend har afvist handlingen, fordi sagens state eller forudsætninger har ændret sig.",
            next_step="Hent den aktuelle version og følg det nye næste skridt.",
            can_refresh=True,
        )

    if exc.status_code == 429:
        return UserFacingAPIError(
            title="DOR er midlertidigt belastet",
            message="Forespørgslen blev ikke gennemført, fordi systemet begrænser belastningen lige nu.",
            next_step="Vent et øjeblik og prøv igen.",
        )

    if exc.status_code >= 500:
        return UserFacingAPIError(
            title="DOR kunne ikke gennemføre handlingen",
            message="Der opstod en serverfejl. Handlingen er ikke bekræftet gennemført.",
            next_step="Prøv igen senere. Hvis problemet fortsætter, kan en administrator se de tekniske detaljer.",
        )

    return UserFacingAPIError(
        title="Handlingen kunne ikke gennemføres",
        message="DOR afviste forespørgslen og har ikke bekræftet nogen ændring.",
        next_step="Kontrollér situationen og prøv igen, eller åbn de tekniske detaljer for fejlkoden.",
    )


def render_api_error(
    exc: DORAPIError,
    *,
    key: str,
    operation: str | None = None,
    technical_details: bool = True,
) -> None:
    """Render human recovery first and keep raw details behind disclosure."""
    feedback = explain_api_error(exc)
    prefix = f"{operation}: " if operation else ""
    st.error(f"**{prefix}{feedback.title}**\n\n{feedback.message}")
    st.caption(f"Næste skridt: {feedback.next_step}")

    if feedback.can_reauthenticate:
        if st.button("Log ind igen", key=f"{key}-reauth", type="primary"):
            from dashboard.state import clear_auth

            clear_auth()
            st.rerun()
    elif feedback.can_refresh:
        if st.button("Hent aktuel version", key=f"{key}-refresh", type="primary"):
            st.rerun()

    if technical_details:
        with st.expander("Tekniske detaljer"):
            st.caption(f"HTTP {exc.status_code}")
            st.code(str(exc))
