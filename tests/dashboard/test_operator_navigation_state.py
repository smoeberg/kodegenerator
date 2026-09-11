from pathlib import Path

APP = Path("dashboard/operator_center.py")
VIEWS = Path("dashboard/case_shell_views.py")


def test_operator_navigation_uses_distinct_widget_and_logical_state_keys() -> None:
    source = APP.read_text(encoding="utf-8")

    assert 'key="operator_nav_widget"' in source
    assert 'key="operator_admin_nav_widget"' in source
    assert 'on_change=_copy_widget_to_logical' in source
    assert 'logical_key="operator_nav"' in source
    assert 'logical_key="operator_admin_nav"' in source


def test_case_buttons_may_change_logical_navigation_after_sidebar_render() -> None:
    views = VIEWS.read_text(encoding="utf-8")
    app = APP.read_text(encoding="utf-8")

    assert 'st.session_state["operator_nav"] = nav' in views
    assert 'st.session_state["operator_admin_nav"] = "Ingen"' in views
    assert 'key="operator_nav_widget"' in app
    assert 'key="operator_admin_nav_widget"' in app
