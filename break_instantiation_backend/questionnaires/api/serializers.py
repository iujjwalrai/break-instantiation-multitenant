from __future__ import annotations

import typing

from rest_framework import serializers

from break_instantiation_backend.questionnaires.models import AnswerTypeChoices
from break_instantiation_backend.questionnaires.models import ConsentRecord
from break_instantiation_backend.questionnaires.models import ConsentTemplate
from break_instantiation_backend.questionnaires.models import Question
from break_instantiation_backend.questionnaires.models import QuestionOption
from break_instantiation_backend.questionnaires.models import Section

_TYPE_FIELD: dict[str, str] = {
    AnswerTypeChoices.SINGLE_CHOICE: "selected_option_id",
    AnswerTypeChoices.MULTI_CHOICE: "selected_option_ids",
    AnswerTypeChoices.FREE_TEXT: "free_text_value",
    AnswerTypeChoices.SCALE: "scale_value",
}


class ConsentTemplateOutSerializer(serializers.ModelSerializer):
    """The active wording a client is shown before they grant consent."""

    class Meta:
        model = ConsentTemplate
        fields = ["id", "version", "text"]


class ConsentRecordOutSerializer(serializers.ModelSerializer):
    template_version = serializers.SerializerMethodField()
    text = serializers.SerializerMethodField()

    class Meta:
        model = ConsentRecord
        fields = ["id", "created_at", "template_version", "text"]

    def get_template_version(self, record: ConsentRecord) -> str | None:
        if record.template_id is None:
            return None
        return record.template.version

    def get_text(self, record: ConsentRecord) -> str | None:
        if record.template_id is None:
            return None
        return record.template.text


class QuestionOptionOutSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuestionOption
        fields = ["id", "code", "label", "display_order"]


class SectionOutSerializer(serializers.ModelSerializer):
    class Meta:
        model = Section
        fields = ["id", "code", "name", "description"]


class QuestionOutSerializer(serializers.ModelSerializer):
    options = serializers.SerializerMethodField()
    section = SectionOutSerializer(read_only=True)

    class Meta:
        model = Question
        fields = [
            "id",
            "code",
            "prompt",
            "subtext",
            "answer_type",
            "is_required",
            "section",
            "options",
        ]

    def get_options(self, question: Question) -> list[typing.Any]:
        if question.answer_type not in (
            AnswerTypeChoices.SINGLE_CHOICE,
            AnswerTypeChoices.MULTI_CHOICE,
        ):
            return []
        return list(
            QuestionOptionOutSerializer(question.options.all(), many=True).data,
        )


class AnswerInSerializer(serializers.Serializer):
    """Validates a submitted answer's shape against `question.answer_type`.

    This is the app-layer half of the spec's two-tier type-integrity rule
    (Decision 5) -- the DB `CheckConstraint` only catches a scalar-field
    collision, not an M2M mismatch or a cross-question option, so this is
    the layer that actually enforces both. `services.submit_answer`
    explicitly does not re-check option ownership; this is where that
    precondition is established before `submit_answer` is ever called.
    """

    question_id = serializers.UUIDField()
    selected_option_id = serializers.UUIDField(required=False)
    selected_option_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
    )
    free_text_value = serializers.CharField(required=False, allow_blank=True)
    # ponytail: bounded to Postgres's int4 range, not a real business range
    # (nobody knows the intended scale yet -- see OPEN_QUESTIONS.md). Just
    # keeps out-of-range input from crashing with a DB overflow; narrow this
    # once real scale question content exists.
    scale_value = serializers.IntegerField(
        required=False,
        min_value=-2_147_483_648,
        max_value=2_147_483_647,
    )

    def validate(self, attrs: dict) -> dict:
        try:
            question = Question.objects.get(pk=attrs["question_id"])
        except Question.DoesNotExist as exc:
            raise serializers.ValidationError(
                {"question_id": "Question not found."},
            ) from exc

        expected_field = _TYPE_FIELD[question.answer_type]
        populated = {
            field
            for field in _TYPE_FIELD.values()
            if attrs.get(field) not in (None, "", [])
        }
        if populated != {expected_field}:
            msg = (
                f"Exactly `{expected_field}` is required for a "
                f"`{question.answer_type}` question."
            )
            raise serializers.ValidationError(msg)

        if expected_field == "selected_option_id":
            option = question.options.filter(pk=attrs["selected_option_id"]).first()
            if option is None:
                raise serializers.ValidationError(
                    {"selected_option_id": "Option does not belong to this question."},
                )
            attrs["selected_option"] = option
        elif expected_field == "selected_option_ids":
            option_ids = attrs["selected_option_ids"]
            options = list(question.options.filter(pk__in=option_ids))
            if len(options) != len(set(option_ids)):
                raise serializers.ValidationError(
                    {
                        "selected_option_ids": (
                            "One or more options do not belong to this question."
                        ),
                    },
                )
            attrs["selected_options"] = options

        attrs["question"] = question
        return attrs
