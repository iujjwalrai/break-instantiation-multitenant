"""The graph routing resolver for `RoutingModel.GRAPH` questionnaires.

The whole runtime is `matches()` plus "first edge in priority order whose
guard matches". Everything else in this module is bookkeeping: walking a
session's recorded answers through that rule, and sizing the progress
denominator.

This module is the single implementation of graph resolution. The editing
tool's preview calls `walk_choices` against a draft version rather than
reimplementing any of it -- a second implementation drifts, and a preview
that drifts from production is worse than no preview.

`live_questions`, `edges_by_question`, `entry_of`, `reachable_from` and
`matches` are public for that reason: they are the shared surface the
editing tool's map and diagnostics build on, so that what the map claims
about routing and what a respondent actually experiences come from the
same code. `_resolve_id` stays private -- callers wanting one transition
want `resolve_next`.
"""

from __future__ import annotations

import typing
from collections import defaultdict
from collections import deque

from .models import Edge
from .models import Question

if typing.TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID

    from .models import Answer
    from .models import QuestionnaireVersion


class RoutingError(Exception):
    """Base class for a questionnaire whose graph cannot be resolved."""


class RoutingCycleError(RoutingError):
    """The walk re-entered a question it had already passed through.

    Unreachable under `RoutingModel.SEQUENCE`, where the walk only ever
    moves forward through `display_order`, but an ordinary authoring
    mistake once edges are explicit. Raised rather than broken out of:
    silently stopping would record a completed assessment that skipped
    everything after the loop.
    """

    def __init__(self, question_code: str) -> None:
        self.question_code = question_code
        super().__init__(
            f"Question {question_code} loops back to a question earlier in "
            f"the same path, so it can't be published.",
        )


class RoutingTargetMissingError(RoutingError):
    """An edge points at a question that is archived, or in another version.

    Also raised rather than treated as the end of the flow. A respondent
    who silently "finishes" early produces an assessment record that looks
    complete and is not, which is harder to detect and worse to correct
    than a loud failure. Activation-time validation is what should stop
    this from ever reaching a respondent; this is the backstop.
    """

    def __init__(self, from_code: str, target_id: UUID) -> None:
        self.from_code = from_code
        self.target_id = target_id
        super().__init__(
            f"Question {from_code} leads to a question that no longer "
            f"exists in this version.",
        )


# Sections whose questions are shown to the respondent together rather than
# one at a time (see `presentation_state`). Deliberately an explicit, named
# allowlist rather than "batch wherever the graph happens to have no
# branching" -- `getting_started` (age/gender) is structurally just as
# unconditional as `timeline`, and batching it too was never asked for. A
# section opts in by content-author decision, not by incidental graph shape.
# Lives here rather than in `services` so `presentation_state` below --
# shared by the real respondent walk and the flow-tool preview -- doesn't
# need `services` to supply it, matching this module's existing
# no-dependency-on-`services` rule (see `walk_choices`'s docstring).
# ponytail: a hardcoded set of codes, not a `Section` model field --
# promote to a real field (and a CSV/flow-tool column) if a second section
# ever needs this rather than just `timeline`.
BATCH_PRESENTATION_SECTION_CODES = frozenset({"timeline", "freeform"})


def selected_option_ids(answer: Answer) -> frozenset[UUID]:
    """Every option `answer` selected, whether single- or multi-choice.

    Resolved once per answer rather than once per candidate edge: reading
    the multi-choice side inside the guard would re-evaluate
    `selected_options` for every edge leaving the question, which is a
    query apiece unless the caller happened to prefetch.
    """
    chosen = {answer.selected_option_id} if answer.selected_option_id else set()
    chosen.update(option.id for option in answer.selected_options.all())
    return frozenset(chosen)


def matches(edge: Edge, chosen: frozenset[UUID]) -> bool:
    """Whether `edge`'s guard is satisfied by the options in `chosen`.

    The one place guard semantics are defined.

    A `from_option` belonging to some other question simply never appears
    in `chosen`, which is why such a row is inert rather than dangerous.
    """
    return edge.from_option_id is None or edge.from_option_id in chosen


def edges_by_question(version_id: UUID) -> dict[UUID, list[Edge]]:
    """Every edge in the version, grouped by source and ordered by priority.

    Loaded in one query and walked in memory: a per-question query inside
    the walk would be one round trip per answered question on every single
    request.
    """
    grouped: dict[UUID, list[Edge]] = defaultdict(list)
    edges = Edge.objects.filter(
        from_question__questionnaire_version_id=version_id,
    ).order_by("priority")
    for edge in edges:
        grouped[edge.from_question_id].append(edge)
    return grouped


def live_questions(version_id: UUID) -> dict[UUID, Question]:
    return {
        question.id: question
        for question in Question.objects.filter(
            questionnaire_version_id=version_id,
            archived_at__isnull=True,
        ).select_related("section")
    }


def _resolve_id(
    from_question: Question,
    chosen: frozenset[UUID],
    edges: list[Edge],
    live: dict[UUID, Question],
) -> UUID | None:
    for edge in edges:
        if not matches(edge, chosen):
            continue
        if edge.to_question_id is None:
            return None
        if edge.to_question_id not in live:
            raise RoutingTargetMissingError(from_question.code, edge.to_question_id)
        return edge.to_question_id
    # No edge matched: the flow ends. There is no positional fall-through
    # to try, by design -- that is what makes a newly added question inert
    # until something is explicitly pointed at it.
    return None


def entry_of(live: dict[UUID, Question]) -> Question | None:
    """The lowest-ordered live question: where a session starts.

    `display_order` is otherwise presentational under GRAPH routing; this
    is the one job it keeps, in the absence of a separate entry marker.
    Expressed over an already-loaded set so `walk` does not re-query for a
    question it is holding, and so there is only one definition of the
    rule to keep correct.
    """
    return min(live.values(), key=lambda question: question.display_order, default=None)


def entry_question(version: QuestionnaireVersion) -> Question | None:
    """The question a session on `version` starts at."""
    return entry_of(live_questions(version.id))


def _find_cycle(
    entry_id: UUID,
    edges: dict[UUID, list[Edge]],
    live: dict[UUID, Question],
) -> UUID | None:
    """The id of a live question that starts a cycle reachable from `entry_id`, if any.

    Standard three-colour DFS over every edge, not just ones a real answer
    would fire -- publish-time validation has no answers to replay, so it
    has to assume any edge could be taken. A node re-encountered while
    still on the current path (`GRAY`) is a genuine back-edge; one already
    finished (`BLACK`) is just two branches reconverging, which `walk`'s
    own `reachable_from` already treats as normal. Iterative, not
    recursive, so a long walk can't hit Python's recursion limit.
    """
    white, gray, black = 0, 1, 2
    color: dict[UUID, int] = dict.fromkeys(live, white)
    color[entry_id] = gray
    stack: list[tuple[UUID, int]] = [(entry_id, 0)]
    while stack:
        question_id, i = stack[-1]
        outgoing = edges.get(question_id, ())
        if i >= len(outgoing):
            color[question_id] = black
            stack.pop()
            continue
        stack[-1] = (question_id, i + 1)
        target_id = outgoing[i].to_question_id
        if target_id is None or target_id not in live:
            continue
        if color[target_id] == gray:
            return target_id
        if color[target_id] == white:
            color[target_id] = gray
            stack.append((target_id, 0))
    return None


def validate_edges(version: QuestionnaireVersion) -> None:
    """Raise if the graph has a dangling edge, or a cycle reachable from the entry.

    Meant to run before a `GRAPH` version is activated -- these are the
    two ways a respondent otherwise crashes mid-walk, on
    `RoutingTargetMissingError`/`RoutingCycleError` respectively. Only
    edges leaving a *live* question matter for either check: `walk` only
    ever stands on a live question (`entry_of`/`live[next_id]` are both
    drawn from `live_questions`), so an edge hanging off an already-dead
    `from_question` can never actually be reached.

    Deliberately stricter than `diagnostics.audit`, which reports the same
    two faults without raising: this refuses to publish over any edge that
    could crash a walk, while the map has to keep drawing a broken graph
    precisely so somebody can see the break and fix it.

    A `routing_protected` question's own outgoing edges are excluded from
    both checks, mirroring break-backend's own `validate_no_routing_cycle`
    exactly (see that field's own docstring): production never actually
    consults that question's `Edge` row at all, short-circuiting into a
    hardcoded phase transition the instant it's reached, so an edge copied
    in from break's real content -- one this checker would otherwise
    dutifully report as a cycle or a dangling target -- is not a fault,
    just dead data that real serving never reads. Meaningless for every
    non-BREAK product, where the field is always `False`.
    """
    live = live_questions(version.id)
    edges = edges_by_question(version.id)
    protected_ids = {
        question_id
        for question_id, question in live.items()
        if question.routing_protected
    }

    for question_id, outgoing in edges.items():
        if question_id not in live or question_id in protected_ids:
            continue
        for edge in outgoing:
            target_id = edge.to_question_id
            if target_id is not None and target_id not in live:
                raise RoutingTargetMissingError(live[question_id].code, target_id)

    entry = entry_of(live)
    if entry is not None:
        cycle_edges = (
            {qid: edges[qid] for qid in edges if qid not in protected_ids}
            if protected_ids
            else edges
        )
        cycle_at = _find_cycle(entry.id, cycle_edges, live)
        if cycle_at is not None:
            raise RoutingCycleError(live[cycle_at].code)


def resolve_next(question: Question, answer: Answer) -> Question | None:
    """The next question after answering `question`, or None if the flow ends.

    The single-step entry point, for callers resolving one transition at a
    time (a preview stepping forward). `walk` is the bulk equivalent and
    shares `matches`, so the two cannot disagree.
    """
    version_id = question.questionnaire_version_id
    live = live_questions(version_id)
    edges = list(question.outgoing_edges.order_by("priority"))
    next_id = _resolve_id(question, selected_option_ids(answer), edges, live)
    return live[next_id] if next_id is not None else None


def unconditional_run(
    start: Question,
    edges: dict[UUID, list[Edge]],
    live: dict[UUID, Question],
) -> list[Question]:
    """`start` plus every question after it whose answer can't change what comes next.

    A client that wants to render several questions together, before any
    of them is answered, can only do that safely where the graph has
    nothing to decide: a question with exactly one outgoing edge and no
    guard on it. Anything else -- a real branch, or an edge scoped to one
    option -- means some answer earlier in the run could change what
    follows, which the client can't have known when it rendered the batch.
    Stops there, at a section boundary, at a `batch_group` boundary within
    the section (several batches can share one section -- see
    `services.BATCH_PRESENTATION_SECTION_CODES` and `Question.batch_group`
    -- so a section boundary alone isn't fine-grained enough), or at the
    end of the flow.
    """
    run = [start]
    current = start
    while True:
        outgoing = edges.get(current.id, [])
        if len(outgoing) != 1 or outgoing[0].from_option_id is not None:
            break
        target_id = outgoing[0].to_question_id
        if target_id is None or target_id not in live:
            break
        next_question = live[target_id]
        if (
            next_question.section_id != start.section_id
            or next_question.batch_group != start.batch_group
        ):
            break
        run.append(next_question)
        current = next_question
    return run


def reachable_from(
    start_id: UUID,
    edges: dict[UUID, list[Edge]],
    live: dict[UUID, Question],
) -> set[UUID]:
    """Every live question reachable from `start_id`, inclusive.

    Used as the progress denominator, and chosen to match how the
    SEQUENCE runtime counts: it over-counts, because a question that a
    later answer will branch past is still reachable now, exactly as such
    a question is still in `_filtered_question_sequence`'s list until its
    rule fires. Both totals therefore shrink as the respondent answers,
    rather than one jumping while the other does not.

    `edges` is a parameter rather than loaded here so a caller can narrow
    it: the walk passes the version's whole edge set, while `diagnostics`
    passes only the edges that can actually fire, which is what makes its
    unreachable-question count honest.
    """
    seen: set[UUID] = set()
    stack = [start_id]
    while stack:
        current = stack.pop()
        if current in seen or current not in live:
            continue
        seen.add(current)
        stack.extend(
            edge.to_question_id
            for edge in edges.get(current, ())
            if edge.to_question_id is not None
        )
    return seen


def _incoming_edges_from(
    start_id: UUID,
    target_id: UUID,
    edges: dict[UUID, list[Edge]],
    live: dict[UUID, Question],
) -> dict[UUID, Edge] | None:
    """BFS from `start_id`, recording the edge taken *into* each node.

    `None` if `target_id` is never reached. Split out of `path_to` only to
    keep that function's own branching readable -- this is the same
    traversal `reachable_from` already does, just keeping the edge that
    got to each node instead of throwing it away.
    """
    incoming: dict[UUID, Edge] = {}
    visited = {start_id}
    queue: deque[UUID] = deque([start_id])
    while queue:
        current_id = queue.popleft()
        if current_id == target_id:
            return incoming
        for edge in edges.get(current_id, ()):
            next_id = edge.to_question_id
            if next_id is None or next_id not in live or next_id in visited:
                continue
            visited.add(next_id)
            incoming[next_id] = edge
            queue.append(next_id)
    return incoming if target_id in visited else None


def _chosen_for_edge(edge: Edge) -> frozenset[UUID]:
    if edge.from_option_id is None:
        return frozenset()
    return frozenset({edge.from_option_id})


def path_to(
    version_id: UUID,
    target_question_id: UUID,
) -> list[tuple[UUID, frozenset[UUID]]] | None:
    """One valid sequence of prior answers reaching `target_question_id`.

    Returned as `(question_id, chosen_options)` pairs in the order they'd
    actually be answered, entry first -- the editing tool's preview feeds
    exactly this shape (minus the target itself) back through
    `walk_choices` to land a reviewer on the changed question directly,
    instead of replaying a whole flow to get there by hand.

    Not a resolver decision, so it cannot become a second one: a BFS over
    the same `edges_by_question` `walk` itself reads
    (`_incoming_edges_from`), then walked backward from the target to the
    entry point. Priority and guard evaluation never come into it -- each
    edge's own `from_option_id` already says exactly which answer fires
    it, so there is nothing here to resolve, only to record. Any one valid
    path is as good as any other, since this only has to land a preview at
    the target, not describe the *one* route production takes.

    None if the target is not live, or not reachable from the entry point
    at all (an unpublished branch behind a not-yet-connected edge, or one
    that publish-time validation would refuse for a dangling target
    elsewhere in the graph).
    """
    live = live_questions(version_id)
    if target_question_id not in live:
        return None
    entry = entry_of(live)
    if entry is None:
        return None
    if entry.id == target_question_id:
        return []

    incoming = _incoming_edges_from(
        entry.id,
        target_question_id,
        edges_by_question(version_id),
        live,
    )
    if incoming is None:
        return None

    chain: list[Edge] = []
    node_id = target_question_id
    while node_id != entry.id:
        edge = incoming[node_id]
        chain.append(edge)
        node_id = edge.from_question_id
    chain.reverse()

    return [(edge.from_question_id, _chosen_for_edge(edge)) for edge in chain]


def _walk(
    version: QuestionnaireVersion,
    chosen_for: Callable[[UUID], frozenset[UUID] | None],
) -> tuple[Question | None, int, int, Question | None]:
    """The walk itself, over whatever supplies the answers.

    `chosen_for(question_id)` returns the options chosen for that
    question, or None if it has not been answered -- and the distinction
    matters, because a free-text answer legitimately chooses no options
    at all. An empty frozenset is an answer; None is the absence of one.

    A callable rather than a plain mapping so the answers are resolved
    only for the questions the walk actually stands on. `walk`'s source is
    `Answer` rows whose `selected_options` costs a query apiece, and a
    session that branched past half the questionnaire should not pay for
    the half it skipped.

    The fourth element is the question the walk stood on immediately
    before the one it returns -- `None` if `chosen_for` answered nothing
    at all. `walk`/`walk_choices` below both drop it, keeping their public
    3-tuple; `walk_choices_with_previous` is the one caller that wants it,
    for `presentation_state`.
    """
    live = live_questions(version.id)
    edges = edges_by_question(version.id)

    current = entry_of(live)
    answered = 0
    previous: Question | None = None
    visited: set[UUID] = set()

    while current is not None:
        if current.id in visited:
            raise RoutingCycleError(current.code)
        visited.add(current.id)

        chosen = chosen_for(current.id)
        if chosen is None:
            remaining = reachable_from(current.id, edges, live)
            return current, answered, answered + len(remaining), previous

        answered += 1
        previous = current
        next_id = _resolve_id(current, chosen, edges.get(current.id, []), live)
        current = live[next_id] if next_id is not None else None

    return None, answered, answered, previous


def walk(
    version: QuestionnaireVersion,
    answer_by_question: dict[UUID, Answer],
) -> tuple[Question | None, int, int]:
    """Follow the recorded answers through the graph.

    Returns `(next_question, answered_count, total_count)` -- the pieces
    of a `SessionState`, kept as a plain tuple so this module does not
    depend on `services` (which depends on this one).
    """

    def chosen_for(question_id: UUID) -> frozenset[UUID] | None:
        answer = answer_by_question.get(question_id)
        return None if answer is None else selected_option_ids(answer)

    return _walk(version, chosen_for)[:3]


def walk_choices(
    version: QuestionnaireVersion,
    chosen_by_question: dict[UUID, frozenset[UUID]],
) -> tuple[Question | None, int, int]:
    """Follow hypothetical answers through the graph: the editing tool's preview.

    The same walk `walk` runs, given options directly instead of read off
    `Answer` rows -- which is the whole point. A preview has no session
    and no recorded answers, and the obvious alternative, writing
    throwaway `Assessment`/`Answer` rows so that `walk` could be called
    unchanged, would put fake respondent data in the tables the product
    reports off.

    What it must not become is a second resolver (spec 1.3). It is not
    one: it and `walk` are the same `_walk`, over the same `_resolve_id`,
    over the same `matches`. The only thing that differs is where the
    chosen options came from, and by the time either reaches the guard
    they are the same `frozenset` of option ids -- which is exactly what
    makes the preview's answer to "what comes next" the production
    answer.
    """
    return _walk(version, chosen_by_question.get)[:3]


def walk_choices_with_previous(
    version: QuestionnaireVersion,
    chosen_by_question: dict[UUID, frozenset[UUID]],
) -> tuple[Question | None, int, int, Question | None]:
    """`walk_choices`, plus the question immediately before what it returns.

    For `presentation_state` below: a stateless preview has no `Answer`
    history to derive "the previous question" from the way
    `services._last_answered_question` does for a real session, so this
    reports the one `_walk` was already standing on right before landing
    on its result -- the same `_walk` `walk_choices` calls, not a second
    determination of it.
    """
    return _walk(version, chosen_by_question.get)


def presentation_state(
    next_question: Question | None,
    previous_question: Question | None,
    version: QuestionnaireVersion,
) -> tuple[bool, tuple[Question, ...]]:
    """Whether `next_question` opens a new section, and what to render for it.

    Shared by the real respondent walk (`services.compute_session_state`)
    and the flow-tool preview (`FlowToolPreviewView`): both already have a
    `(next_question, previous_question)` pair from their own walk, by
    whatever means, and this is pure presentation over the two -- not
    another routing decision, so it carries none of `walk`'s "second
    resolver" concern.

    `next_questions` is `(next_question,)` for everything except a section
    listed in `BATCH_PRESENTATION_SECTION_CODES`, where it is the whole
    unconditional run of questions in that section (see
    `unconditional_run`) -- an explicit per-section opt-in, not just
    wherever the graph happens to have no branching.
    """
    is_new_section = (
        next_question is not None
        and next_question.section_id is not None
        and (
            previous_question is None
            or previous_question.section_id != next_question.section_id
        )
    )
    if next_question is None:
        return is_new_section, ()
    batches = (
        next_question.section is not None
        and next_question.section.code in BATCH_PRESENTATION_SECTION_CODES
    )
    if not batches:
        return is_new_section, (next_question,)
    next_questions = tuple(
        unconditional_run(
            next_question,
            edges_by_question(version.id),
            live_questions(version.id),
        ),
    )
    return is_new_section, next_questions
