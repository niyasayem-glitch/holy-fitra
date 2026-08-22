# Obsidian Skills Integration Research

## Identified repository

The repository intended by the user is [`kepano/obsidian-skills`](https://github.com/kepano/obsidian-skills). It describes itself as Agent Skills for Obsidian and follows the Agent Skills specification for compatible agents. The inspected default branch is `main`; the shallow clone resolved to commit `3d54ea7` during this task.

The repository contains five skills: `obsidian-markdown`, `obsidian-bases`, `json-canvas`, `obsidian-cli`, and `defuddle`. The first four are directly relevant to a second-brain workflow; `defuddle` is a clean web-to-Markdown ingestion utility.

## Capabilities relevant to Holy Fitra

| Skill | Useful capability |
|---|---|
| obsidian-markdown | Wikilinks, embeds, callouts, properties, tags, and Obsidian-flavored Markdown authoring |
| obsidian-bases | Structured `.base` views, filters, formulas, and summaries |
| json-canvas | Canvas nodes, edges, groups, and visual knowledge maps |
| obsidian-cli | Vault file operations, search, backlinks, tags, tasks, properties, plugins, and developer diagnostics |
| defuddle | Clean Markdown extraction from web pages before ingestion |

The repository README documents installation through the skill marketplace, `npx skills`, or manual placement. The CLI skill expects a local Obsidian CLI executable and supports vault/file targeting, search, backlinks, tags, tasks, property updates, and silent note creation.

## License and attribution

The repository includes the MIT License, copyright 2026 Steph Ango (`@kepano`). Any copied or adapted substantial code must preserve the copyright and license notice. The preferred Holy Fitra integration is an adapter and compatibility layer that uses the documented concepts and command contracts rather than copying the repository wholesale.

## Integration decision

Holy Fitra should gain an optional `holyfitra_obsidian.py` adapter with three modes: `index` for read-only deterministic local-vault indexing, `query` for provenance-aware retrieval into `VectorMemory`/`EvidenceLedger`, and `export` for explicit generation of Obsidian Markdown, Bases, and JSON Canvas artifacts. Live CLI operations should be opt-in, capability-gated, and never enabled merely because a vault path exists.

The adapter should exclude `.obsidian/`, hidden files, symlink escapes, binary files, and user-configured private paths by default. It should parse Markdown frontmatter, tags, wikilinks, headings, block IDs, and Markdown links; build deterministic note IDs and backlinks; preserve source path and line spans as provenance; and reject writes unless an explicit write capability is granted.

## Sources

1. [kepano/obsidian-skills repository](https://github.com/kepano/obsidian-skills)
2. [Obsidian Skills README](https://raw.githubusercontent.com/kepano/obsidian-skills/main/README.md)
3. [Obsidian Skills MIT License](https://raw.githubusercontent.com/kepano/obsidian-skills/main/LICENSE)
4. [Obsidian official data storage documentation](https://obsidian.md/help/data-storage)
5. [Obsidian official internal links documentation](https://obsidian.md/help/links)
