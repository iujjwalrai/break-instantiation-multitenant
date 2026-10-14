from unittest.mock import MagicMock

import pytest

from break_instantiation_backend.children.schema import enqueue_for_each_child
from break_instantiation_backend.children.tasks import touch_child
from break_instantiation_backend.results.tasks import score_assessment_task

pytestmark = pytest.mark.django_db


def test_enqueue_for_each_child_skips_public():
    task = MagicMock()
    count = enqueue_for_each_child(task, "payload")
    schemas = {call.args[0] for call in task.delay.call_args_list}
    assert "public" not in schemas
    assert {"test", "ej", "break", "draft"} <= schemas
    assert count == len(schemas)
    for call in task.delay.call_args_list:
        assert call.args[1] == "payload"


def test_touch_child_refuses_without_a_child():
    with pytest.raises(RuntimeError, match="child schema"):
        touch_child("")
    with pytest.raises(RuntimeError, match="child schema"):
        touch_child("public")


def test_score_task_refuses_without_a_child():
    with pytest.raises(RuntimeError, match="child schema"):
        score_assessment_task("", "missing")
