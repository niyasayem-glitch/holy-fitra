# Holy Fitra Obsidian Second Brain

## Purpose

Holy Fitra now includes an optional local-vault adapter inspired by the open-format workflow in [`kepano/obsidian-skills`](https://github.com/kepano/obsidian-skills). The adapter gives AI agents a persistent, inspectable knowledge layer without turning every note into an unquestioned fact.

Obsidian stores notes as Markdown files inside a vault folder, including subfolders, and maintains a metadata cache for its own UI and graph features [1]. Holy Fitra reads the open Markdown representation directly, which keeps the integration usable in Termux and avoids making the compiler depend on the Obsidian application.

## Capabilities

| Capability | Behavior |
|---|---|
| Deterministic indexing | Sorted Markdown discovery, content SHA-256 note identity, stable vault snapshot digest |
| Markdown understanding | Frontmatter, scalar/list tags, headings, block IDs, Wikilinks, and Markdown links |
| Knowledge graph | Resolved outgoing links, unresolved-link reporting, deterministic backlinks, JSON Canvas export |
| Structured views | Obsidian Bases YAML export with note path, tags, links, and backlinks |
| AI retrieval | Case-insensitive lexical search with title/tag bonuses and deterministic snippets |
| Provenance | Every retrieved note carries its vault-relative path and content digest |
| Agent integration | Capability-gated read-only `obsidian.search` tool for `ToolRegistry` |
| Evidence discipline | Imported notes default to `CLAIM`; predictions are rejected, so notes cannot silently become model predictions |
| Write safety | Markdown, Canvas, and Bases writes require the explicit `obsidian.write` capability |
| Path safety | Hidden/configuration directories, symlink escapes, absolute paths, parent traversal, and non-Markdown note writes are rejected |

Obsidian supports Wikilinks such as `[[Note]]`, folder-qualified links, heading links, and block links [2]. Holy Fitra resolves the file target while preserving the original link text and keeps unresolved targets visible in the snapshot rather than inventing notes.

## Usage

```python
from holyfitra_ai_system import ToolRegistry
from holyfitra_obsidian import ObsidianVaultIndex

index = ObsidianVaultIndex("/path/to/vault")
snapshot = index.refresh()
print(snapshot.note_count, snapshot.digest)

hits = index.search("quantized transformer", top_k=5)
for hit in hits:
    print(hit.path, hit.score, hit.provenance)

claims = index.evidence_for("verified Android execution", top_k=4)
context = index.context_pack("self-hosted compiler", max_chars=8000)

registry = ToolRegistry()
index.register_read_tool(registry)
result = registry.invoke(
    "obsidian.search",
    {"query": "Holy Fitra compiler", "top_k": 3},
    grants=frozenset({"obsidian.read"}),
)
```

The read tool returns a `ToolResult` with claim-level evidence and provenance. An agent must still use Holy Fitra’s existing claim verifier before treating a note as support for a tool action. A note is not promoted to `FACT` by the adapter.

## Visual and structured exports

The adapter can export the indexed graph as a `.canvas` artifact and a table-oriented `.base` artifact:

```python
index.export_artifact("AI/knowledge.canvas", kind="canvas", capability="obsidian.write")
index.export_artifact("AI/knowledge.base", kind="base", tag="#ai", capability="obsidian.write")
```

The Canvas output uses stable 16-character hexadecimal IDs, file nodes, and edges whose references are checked against the node set. The Bases output is YAML with a table view and explicit `file.*` properties. Both formats follow the structures described in the verified Obsidian skill repository [3].

## Privacy and safety boundary

The adapter is intentionally local and read-only by default. It excludes `.obsidian`, `.git`, `.trash`, `.github`, and hidden path components; it enforces a maximum note size; and it never follows a symlink outside the vault root. Retrieval is lexical and deterministic, not an opaque remote embedding call.

Writing requires the literal `obsidian.write` capability and is never registered as an agent tool by default. Live Obsidian CLI or Local REST/MCP operations are not silently enabled. They remain optional future connectors that require explicit user configuration and separate capability grants.

## Relationship to the upstream skill

Holy Fitra does not copy the upstream skill repository wholesale. It adopts compatible concepts and open file formats while keeping its own implementation, fail-closed evidence semantics, and deterministic runtime contracts. The upstream repository is MIT-licensed; if future code is copied rather than independently implemented, the upstream copyright and license notice must be preserved [4].

## Current limitations

The adapter does not yet implement Obsidian’s full YAML type system, Dataview formulas, embeds, transclusion rendering, aliases, heading/block-target edits, or semantic vector embeddings. It also does not claim to replace the live Obsidian CLI. These are explicit follow-up features, not hidden assumptions.

## References

[1]: https://obsidian.md/help/data-storage "Obsidian Help: How Obsidian stores data"
[2]: https://obsidian.md/help/links "Obsidian Help: Internal links"
[3]: https://github.com/kepano/obsidian-skills "kepano/obsidian-skills"
[4]: https://raw.githubusercontent.com/kepano/obsidian-skills/main/LICENSE "kepano/obsidian-skills MIT License"
