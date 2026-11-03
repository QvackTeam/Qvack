"""Refresh of a topic's notes by the artifact writer (ТЗ Ф4 WP23.2; Т-§17.3, Т-§17.7; D-C-139).

The job `artifact.topic_refresh` (P2, `lock_key = artifact:{topic}`, stream A's dispatcher rows:
after a session with exposures or evidence on the topic, and after a task closed with hints)
builds the input of `artifact_writer@1` from the four layers of `Т-§17.3`:

1. the system template of the type — the templates are layer 1 of the prompt file itself, the
   input names the type (`notes`);
2. the learner's skill bound to the type — none until WP23.6 (`content.learner_skills`);
3. the context — the topic with its skills, material chunks teaching them (`materials_prefetch`,
   Т-§10.5), the topics it builds on and that build on it (`topic_requires`), and the
   phrasings that worked: the last turn that showed a skill
   (`turn.committed`, `markup.exposures`) before an independent success on it (Т1: a code
   verdict, correct, no help — `skill_history`), chosen by code from the log (`Т-§17.3` п.3);
4. the personal minimum — misconceptions of the topic with quotes, skills where hints were
   needed, skills known firmly (a proven level).

The memory is read only through `GraphReader` (S4, §4.1), built in the job by
`create_graph_reader(ctx.neo4j, ctx.settings)` (D-A-137). Skills and chunks are short labels
(`S1`, `P1`, Т-§4.5). Code checks the output (`Т-§17.3`): an unknown label or a block number that
is not in the current version is a violation — one more generation, then the element is dropped.
The blocks go to `write_system_blocks` (D-C-125): learner blocks are never rewritten. Cards are
WP23.4.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from uuid import UUID

from redis.asyncio import Redis

from quack.artifacts.documents import Block, SystemBlock, get_artifact, write_system_blocks
from quack.artifacts.writer import ArtifactWriterOutput, WrittenBlock
from quack.config import Settings
from quack.db import Db
from quack.graph.read import GraphReader, TopicMemory, create_graph_reader
from quack.graph.read.materials import ChunkHit, materials_prefetch
from quack.jobs.queue import ClaimedJob
from quack.jobs.runner import JobContext, register_job_handler
from quack.llm.gateway import LLMGateway
from quack.llm.labels import LabelKind, LabelMap, UnknownLabelError
from quack.logging import get_logger

log = get_logger(__name__)

WRITER_ROLE = "artifact_writer"
NOTES_TYPE = "notes"
NO_LEARNER_SKILL = "None."

type Prefetch = Callable[[Sequence[UUID]], Awaitable[list[ChunkHit]]]

# Turns that showed one of the skills, newest first (`Т-§17.3` п.3).
_EXPOSING_TURNS = (
    "SELECT seq, payload ->> 'text' AS text, "
    "ARRAY(SELECT e ->> 'skill_id' FROM jsonb_array_elements(payload -> 'markup' -> 'exposures') e"
    ") AS skills "
    "FROM core.events WHERE learner_id = %(learner_id)s AND type = 'turn.committed' "
    "AND EXISTS (SELECT 1 FROM jsonb_array_elements(payload -> 'markup' -> 'exposures') e "
    "WHERE e ->> 'skill_id' = ANY(%(skills)s)) "
    "ORDER BY seq DESC"
)


@dataclass(frozen=True)
class WriterInput:
    variables: dict[str, str]
    labels: LabelMap
    chunks: dict[UUID, ChunkHit]
    current: tuple[Block, ...]


async def worked_phrasings(
    db: Db, reader: GraphReader, *, learner_id: UUID, skill_ids: Sequence[UUID]
) -> dict[UUID, str]:
    """Skill → the text of the last turn that showed it before an independent success (Т1:
    code verdict, correct, no help) on it; skills without such a pair are absent."""
    if not skill_ids:
        return {}
    turns = await db.fetch_all(
        _EXPOSING_TURNS, {"learner_id": learner_id, "skills": [str(s) for s in skill_ids]}
    )
    found: dict[UUID, str] = {}
    for skill_id in skill_ids:
        successes = [
            e.seq
            for e in await reader.skill_history(skill_id)
            if e.source == "code" and e.outcome == "correct" and e.assistance == "none"
        ]
        if not successes:
            continue
        latest = max(successes)
        for turn in turns:
            if turn["seq"] < latest and str(skill_id) in turn["skills"]:
                found[skill_id] = turn["text"]
                break
    return found


async def writer_input(
    db: Db,
    reader: GraphReader,
    prefetch: Prefetch,
    settings: Settings,
    *,
    learner_id: UUID,
    topic_id: UUID,
) -> WriterInput | None:
    """The four layers for the topic's notes; `None` — the graph does not know the topic."""
    memories = await reader.topic_memory([topic_id])
    if not memories:
        return None
    topic = memories[0]
    skill_ids = [s.skill_id for s in topic.skills]
    hits = await prefetch(skill_ids)
    labels = LabelMap.build(
        settings,
        skills=skill_ids,
        chunks=[h.chunk_id for h in hits],
        misconceptions=[m.misconception_id for m in topic.misconceptions],
    )
    phrasings = await worked_phrasings(db, reader, learner_id=learner_id, skill_ids=skill_ids)
    hinted = [s for s in skill_ids if await needed_hints(reader, s)]
    notes = await get_artifact(db, learner_id=learner_id, kind="notes", owner_id=topic_id)
    variables = {
        "artifact_type": NOTES_TYPE,
        "learner_skill": NO_LEARNER_SKILL,
        "topic_graph": _topic_graph(topic, labels, await _neighbours(reader, topic)),
        "material_chunks": chunks_text(hits, labels),
        "worked_phrasings": phrasings_text(phrasings, labels),
        "personal": personal_text(topic, labels, hinted),
        "current_blocks": numbered_blocks_text(notes.blocks),
    }
    return WriterInput(
        variables=variables,
        labels=labels,
        chunks={h.chunk_id: h for h in hits},
        current=notes.blocks,
    )


async def needed_hints(reader: GraphReader, skill_id: UUID) -> bool:
    return any(e.assistance != "none" for e in await reader.skill_history(skill_id))


def _label(labels: LabelMap, kind: LabelKind, object_id: UUID) -> str | None:
    return labels.label(kind, object_id)


async def _neighbours(reader: GraphReader, topic: TopicMemory) -> tuple[list[str], list[str]]:
    """The topic graph (`REQUIRES` between topics, Т-§4.6): names of the topics this one builds
    on and of those that build on it."""
    if topic.domain_id is None:
        return [], []
    links = await reader.topic_requires(topic.domain_id)
    needs = [link.to_topic_id for link in links if link.from_topic_id == topic.topic_id]
    needed_by = [link.from_topic_id for link in links if link.to_topic_id == topic.topic_id]
    if not needs and not needed_by:
        return [], []
    names = {t.topic_id: t.name for t in await reader.topic_memory([*needs, *needed_by])}
    return [names[t] for t in needs if t in names], [names[t] for t in needed_by if t in names]


def _topic_graph(
    topic: TopicMemory, labels: LabelMap, neighbours: tuple[list[str], list[str]]
) -> str:
    lines = [f"Topic: {topic.name}", "Skills:"]
    for skill in topic.skills:
        label = _label(labels, "skill", skill.skill_id)
        if label is not None:
            lines.append(f"- {label}: {skill.name or 'unnamed skill'}")
    needs, needed_by = neighbours
    if needs:
        lines.append("Builds on: " + ", ".join(needs))
    if needed_by:
        lines.append("Needed for: " + ", ".join(needed_by))
    return "\n".join(lines)


def chunks_text(hits: Sequence[ChunkHit], labels: LabelMap) -> str:
    if not hits:
        return "None."
    out = []
    for hit in hits:
        where = f"page {hit.page}" if hit.page is not None else "no page"
        out.append(f"{_label(labels, 'chunk', hit.chunk_id)} ({where}):\n> {hit.text}")
    return "\n\n".join(out)


def phrasings_text(found: dict[UUID, str], labels: LabelMap) -> str:
    lines = [
        f"{label}: {text}"
        for skill_id, text in found.items()
        if (label := _label(labels, "skill", skill_id)) is not None
    ]
    return "\n\n".join(lines) or "None."


def personal_text(topic: TopicMemory, labels: LabelMap, hinted: Sequence[UUID]) -> str:
    lines: list[str] = []
    for m in topic.misconceptions:
        quotes = "; ".join(f'"{q}"' for q in m.quotes)
        lines.append(
            f"Misconception {_label(labels, 'misconception', m.misconception_id)}: {m.statement}"
            + (f" — in the learner's words: {quotes}" if quotes else "")
        )
    hints = [label for s in hinted if (label := _label(labels, "skill", s)) is not None]
    if hints:
        lines.append("Hints were needed on: " + ", ".join(hints))
    firm = [
        label
        for s in topic.skills
        if any(level.status == "proven" for level in s.levels)
        and (label := _label(labels, "skill", s.skill_id)) is not None
    ]
    if firm:
        lines.append("Known firmly: " + ", ".join(firm))
    return "\n".join(lines) or "None."


def numbered_blocks_text(blocks: Sequence[Block]) -> str:
    if not blocks:
        return "None yet."
    return "\n\n".join(
        f"{n}. [{block.kind}, {block.owner}]\n{block.content}" for n, block in enumerate(blocks, 1)
    )


def system_blocks(
    written: Sequence[WrittenBlock], context: WriterInput
) -> tuple[list[SystemBlock], int]:
    """The writer's blocks with ids instead of labels, and the number of violating ones."""
    blocks: list[SystemBlock] = []
    bad = 0
    for item in written:
        try:
            blocks.append(_system_block(item, context))
        except (UnknownLabelError, IndexError):
            bad += 1
    return blocks, bad


def _system_block(item: WrittenBlock, context: WriterInput) -> SystemBlock:
    target = None
    if item.updates is not None:
        if item.updates > len(context.current):
            raise IndexError(item.updates)
        target = context.current[item.updates - 1].block_id
    sources = []
    for label in item.sources:
        hit = context.chunks[context.labels.resolve("chunk", label)]
        sources.append(
            {
                "chunk_id": str(hit.chunk_id),
                "material_id": str(hit.material_id) if hit.material_id else None,
                "page": hit.page,
            }
        )
    skills = [str(context.labels.resolve("skill", label)) for label in item.skills]
    return SystemBlock(
        block_id=target, kind=item.kind, content=item.content, sources=sources, skills=skills
    )


async def refresh_topic_notes(
    db: Db,
    gateway: LLMGateway,
    reader: GraphReader,
    prefetch: Prefetch,
    settings: Settings,
    *,
    learner_id: UUID,
    topic_id: UUID,
    key: str,
    redis: Redis | None = None,
) -> int | None:
    """A new version of the topic's notes; returns it, or `None` — nothing to write (the graph
    does not know the topic, or no valid block came back). A repeated job reads the same answer
    through the outbox and writes no new version (D-C-125 п.4)."""
    context = await writer_input(
        db, reader, prefetch, settings, learner_id=learner_id, topic_id=topic_id
    )
    if context is None:
        log.info("topic_refresh_unknown_topic", topic_id=str(topic_id))
        return None
    prompt = settings.llm_roles[WRITER_ROLE].prompt  # `artifact_writer@N`, §0.4
    if prompt is None:
        raise ValueError("role 'artifact_writer' has no prompt")
    blocks: list[SystemBlock] = []
    for attempt in range(2):  # Т-§17.3: a violation — one more generation, then dropped
        result = await gateway.generate_structured(
            WRITER_ROLE,
            int(prompt.rsplit("@", 1)[1]),
            ArtifactWriterOutput,
            context.variables,
            learner_id,
            None,
            None,
            f"artifact_writer:notes:{topic_id}:{key}" + (":retry" if attempt else ""),
        )
        blocks, bad = system_blocks(result.value.blocks, context)
        if bad == 0:
            break
        log.info("artifact_writer_violations", topic_id=str(topic_id), bad=bad, attempt=attempt)
    if not blocks:
        return None
    notes = await write_system_blocks(
        db,
        learner_id=learner_id,
        kind="notes",
        owner_id=topic_id,
        blocks=blocks,
        created_by=prompt,
        redis=redis,
    )
    return notes.version


@register_job_handler("artifact.topic_refresh")
async def _topic_refresh_handler(job: ClaimedJob, ctx: JobContext) -> None:
    learner_id = job.learner_id
    if learner_id is None:
        raise ValueError("artifact.topic_refresh without a learner")

    async def prefetch(skill_ids: Sequence[UUID]) -> list[ChunkHit]:
        return await materials_prefetch(
            ctx.neo4j, learner_id=learner_id, skill_ids=skill_ids, k=ctx.settings.materials_k
        )

    reader = create_graph_reader(ctx.neo4j, ctx.settings, learner_id=learner_id)  # D-A-144
    await refresh_topic_notes(
        ctx.db, ctx.llm, reader, prefetch, ctx.settings,
        learner_id=learner_id, topic_id=UUID(job.payload["topic_id"]), key=str(job.id),
        redis=ctx.redis,
    )  # fmt: skip
