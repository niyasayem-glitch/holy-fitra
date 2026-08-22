"""Obsidian second-brain integration for Holy Fitra.

The adapter is inspired by the open-format workflow documented by
kepano/obsidian-skills, but does not copy its implementation. It indexes a
local vault read-only by default and converts notes into deterministic,
provenance-bearing retrieval results for Holy Fitra agents.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from holyfitra_ai_system import Evidence, EvidenceKind, ToolRegistry, ToolResult, ToolSpec


class ObsidianError(ValueError):
    """Raised when a vault or second-brain contract is invalid."""


@dataclass(frozen=True)
class ObsidianNote:
    path: str
    title: str
    content: str
    frontmatter: dict[str, Any]
    tags: tuple[str, ...]
    outgoing_links: tuple[str, ...]
    headings: tuple[tuple[str, int], ...]
    block_ids: tuple[tuple[str, int], ...]
    digest: str

    def __post_init__(self) -> None:
        if not self.path or not self.title or not self.digest:
            raise ObsidianError("invalid Obsidian note identity")
        if len(self.digest) != 64 or any(character not in "0123456789abcdef" for character in self.digest):
            raise ObsidianError("note digest must be lowercase SHA-256")

    @property
    def provenance(self) -> tuple[str, ...]:
        return (f"obsidian:{self.path}", f"sha256:{self.digest}")


@dataclass(frozen=True)
class ObsidianHit:
    path: str
    title: str
    score: float
    snippet: str
    provenance: tuple[str, ...]
    tags: tuple[str, ...]


@dataclass(frozen=True)
class VaultSnapshot:
    root: str
    note_count: int
    digest: str
    unresolved_links: tuple[str, ...]


class ObsidianVaultIndex:
    """Deterministic read-only index over an Obsidian Markdown vault."""

    _WIKILINK = re.compile(r"(?<!!)\[\[([^\]]+)\]\]")
    _MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
    _TAG = re.compile(r"(?<![\w])#([A-Za-z0-9_/-]+)")
    _HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
    _BLOCK = re.compile(r"\^([A-Za-z0-9-]+)\s*$")
    _TOKEN = re.compile(r"[A-Za-z0-9_]+")
    _DEFAULT_EXCLUDED = frozenset({".obsidian", ".git", ".trash", ".github"})

    def __init__(self, root: str | Path, *, excluded_directories: Iterable[str] = (), max_note_bytes: int = 4 * 1024 * 1024):
        root_path = Path(root).expanduser().resolve()
        if not root_path.is_dir():
            raise ObsidianError(f"vault root is not a directory: {root_path}")
        if max_note_bytes <= 0:
            raise ObsidianError("max_note_bytes must be positive")
        self.root = root_path
        self.excluded_directories = self._DEFAULT_EXCLUDED.union(str(value) for value in excluded_directories)
        self.max_note_bytes = int(max_note_bytes)
        self._notes: dict[str, ObsidianNote] = {}
        self._backlinks: dict[str, tuple[str, ...]] = {}
        self._unresolved: tuple[str, ...] = ()
        self._snapshot: VaultSnapshot | None = None

    @property
    def notes(self) -> tuple[ObsidianNote, ...]:
        return tuple(self._notes[path] for path in sorted(self._notes))

    @property
    def snapshot(self) -> VaultSnapshot | None:
        return self._snapshot

    def refresh(self) -> VaultSnapshot:
        notes: dict[str, ObsidianNote] = {}
        for candidate in sorted(self.root.rglob("*.md"), key=lambda item: item.as_posix()):
            relative = self._safe_relative(candidate)
            if relative is None or any(part in self.excluded_directories or part.startswith(".") for part in Path(relative).parts):
                continue
            if candidate.stat().st_size > self.max_note_bytes:
                raise ObsidianError(f"note exceeds max_note_bytes: {relative}")
            content = candidate.read_text(encoding="utf-8")
            notes[relative] = self._parse_note(relative, content)
        self._notes = notes
        self._build_backlinks()
        unresolved = sorted({target for note in notes.values() for target in note.outgoing_links if self._resolve_target(target) is None})
        self._unresolved = tuple(unresolved)
        digest = hashlib.sha256()
        for note in self.notes:
            digest.update(note.path.encode("utf-8"))
            digest.update(note.digest.encode("ascii"))
        self._snapshot = VaultSnapshot(str(self.root), len(notes), digest.hexdigest(), self._unresolved)
        return self._snapshot

    def get(self, path: str) -> ObsidianNote:
        if not self._notes:
            self.refresh()
        normalized = self._normalize_path(path)
        resolved = normalized if normalized in self._notes else self._resolve_target(normalized)
        if resolved is None:
            raise ObsidianError(f"note not found: {path}")
        return self._notes[resolved]

    def search(self, query: str, *, top_k: int = 5) -> tuple[ObsidianHit, ...]:
        if not query or not query.strip():
            raise ObsidianError("search query must be non-empty")
        if top_k <= 0:
            raise ObsidianError("top_k must be positive")
        if not self._notes:
            self.refresh()
        query_tokens = self._tokens(query)
        scored: list[ObsidianHit] = []
        for note in self.notes:
            content_tokens = self._tokens(note.content)
            title_tokens = self._tokens(note.title)
            tag_tokens = self._tokens(" ".join(note.tags))
            overlap = len(query_tokens.intersection(content_tokens)) / max(1, len(query_tokens))
            title_bonus = 0.25 * len(query_tokens.intersection(title_tokens)) / max(1, len(query_tokens))
            tag_bonus = 0.10 * len(query_tokens.intersection(tag_tokens)) / max(1, len(query_tokens))
            score = overlap + title_bonus + tag_bonus
            if score <= 0.0:
                continue
            scored.append(ObsidianHit(note.path, note.title, float(score), _snippet(note.content, query_tokens), note.provenance, note.tags))
        scored.sort(key=lambda hit: (-hit.score, hit.path))
        return tuple(scored[:top_k])

    def backlinks_for(self, path: str) -> tuple[ObsidianNote, ...]:
        if not self._notes:
            self.refresh()
        normalized = self._normalize_path(path)
        resolved = normalized if normalized in self._notes else self._resolve_target(normalized)
        if resolved is None:
            return ()
        return tuple(self._notes[item] for item in self._backlinks.get(resolved, ()))

    def evidence_for(self, query: str, *, top_k: int = 5, kind: EvidenceKind = EvidenceKind.CLAIM) -> tuple[Evidence, ...]:
        if kind is EvidenceKind.PREDICTION:
            raise ObsidianError("Obsidian notes cannot be imported as predictions")
        evidence: list[Evidence] = []
        for hit in self.search(query, top_k=top_k):
            evidence_id = f"obsidian:{hit.path}:{hashlib.sha256(hit.snippet.encode('utf-8')).hexdigest()[:16]}"
            confidence = max(0.0, min(1.0, hit.score))
            evidence.append(Evidence(evidence_id, kind, hit.snippet, confidence, hit.provenance))
        return tuple(evidence)

    def context_pack(self, query: str, *, top_k: int = 5, max_chars: int = 12000) -> str:
        if max_chars <= 0:
            raise ObsidianError("max_chars must be positive")
        sections: list[str] = []
        used = 0
        for hit in self.search(query, top_k=top_k):
            section = f"## {hit.title}\nSource: {hit.path}\nScore: {hit.score:.6f}\n\n{hit.snippet.strip()}\n"
            if used + len(section) > max_chars:
                break
            sections.append(section)
            used += len(section)
        return "\n".join(sections)

    def canvas(self) -> dict[str, Any]:
        if not self._notes:
            self.refresh()
        nodes: list[dict[str, Any]] = []
        node_ids: dict[str, str] = {}
        for index, note in enumerate(self.notes):
            node_id = hashlib.sha256(f"obsidian-node:{note.path}".encode("utf-8")).hexdigest()[:16]
            node_ids[note.path] = node_id
            nodes.append({"id": node_id, "type": "file", "x": (index % 4) * 440, "y": (index // 4) * 280, "width": 380, "height": 220, "file": note.path})
        edges: list[dict[str, Any]] = []
        for note in self.notes:
            for target in note.outgoing_links:
                resolved = self._resolve_target(target)
                if resolved is None or resolved not in node_ids:
                    continue
                edge_id = hashlib.sha256(f"obsidian-edge:{note.path}:{resolved}".encode("utf-8")).hexdigest()[:16]
                edges.append({"id": edge_id, "fromNode": node_ids[note.path], "toNode": node_ids[resolved], "toEnd": "arrow"})
        edges.sort(key=lambda edge: (edge["fromNode"], edge["toNode"], edge["id"]))
        return {"nodes": nodes, "edges": edges}

    def canvas_json(self) -> str:
        return json.dumps(self.canvas(), sort_keys=True, separators=(",", ":"))

    def bases_yaml(self, *, tag: str | None = None) -> str:
        if tag is not None and (not tag or any(character in tag for character in "\\\"\n")):
            raise ObsidianError("invalid Bases tag filter")
        filter_line = f'filters: \'file.hasTag("{tag.lstrip("#")}")\'' if tag else 'filters: \'file.ext == "md"\''
        return "\n".join((
            filter_line,
            "properties:",
            '  file.name:',
            '    displayName: "Note"',
            '  file.path:',
            '    displayName: "Path"',
            '  file.tags:',
            '    displayName: "Tags"',
            '  file.links:',
            '    displayName: "Links"',
            '  file.backlinks:',
            '    displayName: "Backlinks"',
            "views:",
            '  - type: table',
            '    name: "Holy Fitra Second Brain"',
            "    order:",
            "      - file.name",
            "      - file.path",
            "      - file.tags",
            "      - file.links",
            "      - file.backlinks",
            "",
        ))

    def export_artifact(self, relative_path: str, *, kind: str, capability: str | None = None, tag: str | None = None) -> Path:
        if capability != "obsidian.write":
            raise PermissionError("Obsidian artifact writes require the obsidian.write capability")
        normalized = self._normalize_path(relative_path)
        destination = (self.root / normalized).resolve()
        if self.root not in destination.parents:
            raise ObsidianError("artifact path escapes vault root")
        if kind == "canvas" and destination.suffix == ".canvas":
            payload = json.dumps(self.canvas(), sort_keys=True, indent=2) + "\\n"
        elif kind == "base" and destination.suffix == ".base":
            payload = self.bases_yaml(tag=tag)
        else:
            raise ObsidianError("artifact kind and extension do not match")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(payload, encoding="utf-8")
        self._notes = {}
        self.refresh()
        return destination

    def register_read_tool(self, registry: ToolRegistry, *, capability: str = "obsidian.read") -> None:
        if not capability:
            raise ObsidianError("Obsidian read capability must be non-empty")

        def validate(arguments: dict[str, Any]) -> bool:
            query = arguments.get("query")
            top_k = arguments.get("top_k", 5)
            return isinstance(query, str) and bool(query.strip()) and isinstance(top_k, int) and not isinstance(top_k, bool) and 0 < top_k <= 32

        def handle(arguments: dict[str, Any]) -> ToolResult:
            query = str(arguments["query"])
            top_k = int(arguments.get("top_k", 5))
            snapshot = self.snapshot or self.refresh()
            hits = self.search(query, top_k=top_k)
            context = self.context_pack(query, top_k=top_k)
            if not context:
                context = "No matching Obsidian notes found."
            provenance = [f"obsidian:vault:{snapshot.digest}"]
            provenance.extend(item for hit in hits for item in hit.provenance)
            return ToolResult(context, EvidenceKind.CLAIM, 0.5, tuple(dict.fromkeys(provenance)))

        registry.register(ToolSpec("obsidian.search", capability, handle, validate))

    def write_note(self, relative_path: str, content: str, *, capability: str | None = None) -> ObsidianNote:
        if capability != "obsidian.write":
            raise PermissionError("Obsidian writes require the obsidian.write capability")
        if not isinstance(content, str) or not content:
            raise ObsidianError("note content must be non-empty text")
        normalized = self._normalize_path(relative_path)
        destination = (self.root / normalized).resolve()
        if self.root not in destination.parents or destination.suffix.lower() != ".md":
            raise ObsidianError("note path must remain inside the vault and use .md")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
        self._notes = {}
        self.refresh()
        return self.get(normalized)

    def _build_backlinks(self) -> None:
        backlinks: dict[str, list[str]] = {}
        for note in self.notes:
            for target in note.outgoing_links:
                resolved = self._resolve_target(target)
                if resolved is not None:
                    backlinks.setdefault(resolved, []).append(note.path)
        self._backlinks = {target: tuple(sorted(set(sources))) for target, sources in backlinks.items()}

    def _resolve_target(self, target: str) -> str | None:
        normalized = _normalize_link_target(target)
        if not normalized:
            return None
        direct = normalized if normalized.endswith(".md") else normalized + ".md"
        if direct in self._notes:
            return direct
        candidates = [path for path in self._notes if Path(path).stem.casefold() == Path(normalized).name.casefold()]
        if len(candidates) == 1:
            return candidates[0]
        return None

    def _parse_note(self, relative: str, content: str) -> ObsidianNote:
        frontmatter, body = _parse_frontmatter(content)
        lines = content.splitlines()
        headings = tuple((match.group(2), line_number) for line_number, line in enumerate(lines, start=1) if (match := self._HEADING.match(line)))
        block_ids = tuple((match.group(1), line_number) for line_number, line in enumerate(lines, start=1) if (match := self._BLOCK.search(line)))
        links = set()
        links.update(match.group(1) for match in self._WIKILINK.finditer(body))
        links.update(match.group(1) for match in self._MARKDOWN_LINK.finditer(body) if not _is_external_link(match.group(1)))
        frontmatter_tags = frontmatter.get("tags", ())
        if isinstance(frontmatter_tags, str):
            frontmatter_tags = (frontmatter_tags,)
        tags = {str(value).lstrip("#") for value in frontmatter_tags if value}
        tags.update(match.group(1) for match in self._TAG.finditer(body))
        title = str(frontmatter.get("title") or (headings[0][0] if headings else Path(relative).stem))
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return ObsidianNote(relative, title, content, frontmatter, tuple(sorted(tags)), tuple(sorted(links)), headings, block_ids, digest)

    def _safe_relative(self, candidate: Path) -> str | None:
        try:
            resolved = candidate.resolve()
            if self.root not in resolved.parents:
                return None
            return resolved.relative_to(self.root).as_posix()
        except (OSError, ValueError):
            return None

    def _normalize_path(self, path: str) -> str:
        if not isinstance(path, str) or not path or "\\x00" in path:
            raise ObsidianError("invalid vault path")
        candidate = (self.root / path).resolve()
        if self.root not in candidate.parents:
            raise ObsidianError("vault path escapes root")
        return candidate.relative_to(self.root).as_posix()

    @classmethod
    def _tokens(cls, text: str) -> frozenset[str]:
        return frozenset(token.casefold() for token in cls._TOKEN.findall(text))


def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    if not content.startswith("---\n"):
        return {}, content
    end = content.find("\n---", 4)
    if end < 0:
        return {}, content
    raw = content[4:end].splitlines()
    values: dict[str, Any] = {}
    for line in raw:
        if not line.strip() or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            values[key] = tuple(item.strip().strip("'\"") for item in value[1:-1].split(",") if item.strip())
        else:
            values[key] = value.strip("'\"")
    return values, content[end + 4 :].lstrip("\n")


def _normalize_link_target(target: str) -> str:
    value = target.strip().split("|", 1)[0].split("#", 1)[0].strip()
    if value.startswith("/") or ".." in Path(value).parts:
        return ""
    return value.replace("\\", "/")


def _is_external_link(target: str) -> bool:
    return target.startswith(("http://", "https://", "mailto:", "#"))


def _snippet(content: str, query_tokens: frozenset[str], *, width: int = 480) -> str:
    lines = content.splitlines()
    for line in lines:
        if query_tokens.intersection(ObsidianVaultIndex._tokens(line)):
            return line[:width]
    return content.strip()[:width]


__all__ = ["ObsidianError", "ObsidianHit", "ObsidianNote", "ObsidianVaultIndex", "VaultSnapshot"]
