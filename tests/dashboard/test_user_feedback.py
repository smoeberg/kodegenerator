from dashboard.api_client import DORAPIError
from dashboard.user_feedback import explain_api_error


def test_expired_session_offers_reauthentication() -> None:
    feedback = explain_api_error(DORAPIError(401, "expired"))

    assert feedback.title == "Din session er udløbet"
    assert feedback.can_reauthenticate is True
    assert "Log ind igen" in feedback.next_step


def test_fingerprint_mismatch_becomes_refresh_guidance() -> None:
    feedback = explain_api_error(
        DORAPIError(409, "expected_project_fingerprint mismatch")
    )

    assert feedback.title == "Sagen er ændret siden du åbnede den"
    assert feedback.can_refresh is True
    assert "aktuelle version" in feedback.next_step


def test_authority_deny_is_explained_as_missing_access() -> None:
    feedback = explain_api_error(DORAPIError(403, "authority denied"))

    assert feedback.title == "Du har ikke adgang til denne handling"
    assert "administrator" in feedback.next_step


def test_budget_failure_is_explained_without_raw_status_code() -> None:
    feedback = explain_api_error(
        DORAPIError(409, "patch exceeds the approved changed-line budget")
    )

    assert feedback.title == "Omfanget er for stort"
    assert "Reducer scope" in feedback.next_step


def test_validation_error_names_relevant_fields() -> None:
    feedback = explain_api_error(
        DORAPIError(
            422,
            "validation failed",
            {
                "detail": [
                    {"loc": ["body", "intent", "goal"], "msg": "required"},
                    {"loc": ["body", "name"], "msg": "required"},
                ]
            },
        )
    )

    assert feedback.title == "Oplysningerne er ikke gyldige"
    assert "intent.goal" in feedback.message
    assert "name" in feedback.message


def test_server_failure_never_claims_mutation_succeeded() -> None:
    feedback = explain_api_error(DORAPIError(500, "database exploded"))

    assert feedback.title == "DOR kunne ikke gennemføre handlingen"
    assert "ikke bekræftet gennemført" in feedback.message
