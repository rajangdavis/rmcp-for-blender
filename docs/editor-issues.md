# raj editor issues found driving it from an agent session

Context: an agent in a container driving `raj ctl` over TCP against an editor on
the user's machine, editing one DSL file and building it with a compiler that
reads **disk**. Ordered by how much each one cost.

Defects fixed since are condensed to a line of history where the lesson still
has value. Numbers are the originals and do not shift — nothing has been dropped.

## 1. `save` can compose two writers' text into one malformed line

The expensive one. A user edit (`has_names = !apply_to.nil?`) and an agent edit
that deleted the neighbouring `has_names` line interleaved at the same place;
after the user saved, the file on disk contained:

```
      has_names = !apply_to.nil?      names = apply_to || []
```

Two statements on one line. The compiler then failed with
`blender.rmcp.rb:391:39: syntax error: unexpected local variable or method,
expecting end-of-input`, and column 39 is exactly the second `names`.

Cost: several round trips, and a near-miss misdiagnosis — the agent first blamed
the `Module.call(x) != literal` form and rewrote working code because the error
pointed at a line that was correct *in the buffer*.

Evidence: `raj ctl read --json F | jq -r .text > /tmp/buf.rb && diff /tmp/buf.rb F`
showed exactly two hunks — `390a391 > has_names = …      names = apply_to || []`
and a trailing blank line the buffer had and the disk lacked.

A second, quieter symptom in the same session: after six agent edits had been
accepted (`pending=0`, `status` blaming only rejected sets), the save wrote
**none** of them. The buffer/disk diff showed the whole refactor missing and the
build compiled the old text, so the agent had to compare buffer against disk to
discover that its own accepted work was never written.

So a save can both glue two writers' text into one line *and* silently omit an
accepted set. In both cases the build reads text nobody wrote.

**Workaround that worked:** treat the buffer as the source of truth and write it
to disk before building —
`raj ctl read --json F | jq -r .text > F`, then build. It is the only reliable
pattern found in the session, and it needs no save at all.

**Suggest:** when runs from two authors interleave at one line, surface a
conflict (or refuse the save) rather than composing them into a line the parser
rejects. A line-level "two writers here" marker would have saved the whole
detour. And have `status` distinguish "the disk is behind the buffer" from "the
buffer holds undisposed sets", because only the first is a build hazard.

## 2. No way to read the bytes on disk when a buffer shadows the path

`read` and `search` answer from the buffer; there is no `read --disk`. The build
reads disk, so the agent cannot see what will actually be compiled — which turns
every "the compiler says line N" into guesswork about *which* version line N is.

Workaround used: the user ran `raj ctl read --json F | jq -r .text > F` to force
disk == buffer once.

**Suggest:** a `read --disk` (or `version --disk`), and have `status` report the
buffer-vs-disk divergence in bytes so the two can be compared without shelling
out.

## 3. Stale generated-file buffers shadowing reads, and `save --all` over generated output — fixed

`build/**/src/main.rs` and `src/blender_bridge.rs` were left as headless buffers
from earlier reads; a later build rewrote them on disk, and the buffers kept the
pre-build text. The sharp half was that a `save --all` could write that stale
text back over the freshly generated sources. That is guarded now: `save`
refuses to overwrite a file that changed on disk unless `--force` is given, and
`reload` takes the disk version. Reads answering from the buffer is by design.

## 4. LSP results are cached per referring document, and `ok` is not "it compiles"

- Bindings and `rust_file` resolve from **disk** and are cached per referring
  document. A binding saved after the server was first analysed is not picked up
  until that document has a *real* edit: a no-op `apply` does not invalidate it,
  while append-then-delete a newline does.
- `lsp diagnostics` returned `{"status":"ok"}` for a file the DSL compiler then
  rejected with a syntax error (the DSL's Ruby subset is stricter than ruby-lsp).
  It also returns `{"status":"stale","detail":"the language server's last publish
  carried no version and does not describe the current text"}` — easy to read as
  "fine" when it means "no reading at all".

**Suggest:** treat any non-`ok` status as "unknown", and consider surfacing the
DSL parser's own syntax check through the same verb, since that is what the build
will say.

## 5. `open --create` makes a buffer, not a file

`open --create blender_bridge.rs` reported `created`, and the buffer was
writable — but the path was not on disk, so the DSL's `rust_file "blender_bridge.rs"`
reported `rust_file not found: blender_bridge.rs` until the user saved it. The
checker reads disk; the create reply reads like the file exists.

**Suggest:** say in the create reply that the path reaches disk only on save, or
have disk-reading checks consult open buffers too.

## 6. Rejected zero-width change sets deadlocking `clear` — fixed

Two rejected sets, one zero-width, blocked each other
(`cannot be cleared: change set 48 … overlaps it`) and left `status` not-ready
indefinitely, naming a "clear to dispose" that was refused. `clear --all` now
purges a buffer's rejected and invalid sets in one step, workspace-wide with
`--everywhere` — the disposal this entry asked for.

## 7. The claim set is in-memory and resets on restart

After an editor restart, six consecutive edits failed with
`apply: claim a file first` — indistinguishable from never having claimed. (The
skill does say "re-claim after a restart"; the refusal does not.)

**Suggest:** name the reset in the refusal ("claim set empty; set it again"), or
key the claim to the identity rather than the process.

## 8. `--hunks` needs compact JSON Lines

`jq -n --rawfile t f '{start:0,end:0,text:$t}'` (pretty-printed by default) fails
with `--hunks line 1: unexpected end of JSON input`; `jq -nc` works. The flag is
documented as JSON Lines, but the failure reads like malformed JSON rather than
"your object spans several lines".

**Suggest:** accept a pretty-printed single object, or say which line was
incomplete.

## 9. `groups` plain output is tab-separated with multi-word fields

`1<TAB>author 13<TAB>accepted<TAB>2 ops<TAB>…` — so `awk '{print $3}'` yields
`13`, not the state, and a filter for the state silently matched nothing. The
agent briefly mis-read which sets were pending.

**Suggest:** document the columns in `--help`, or make the plain form
whitespace-safe; `--json` is the reliable interface.

## 10. `exec` over TCP with an unmounted sandbox — documented

The container section no longer claims the workspace is mounted: it states there
is no shared filesystem, that `exec` is refused over TCP by design, and it puts
the `-v "$PWD:/workspace"` mount in the run setup, so the cost is visible before
a session shapes around it.

## 11. Two writers on one file, and a copy that truncates first, cost the file

The expensive one, and it was self-inflicted: a background review agent was
launched against the same buffer the user was saving and building. The sequence
that lost the file:

1. two agents wrote to `blender.rmcp.rb` while the user was saving it;
2. the result was written to disk by a copy idiom that truncates **before** the
   pipeline runs:

   ```bash
   raj ctl read --json F | jq -r .text > F     # the shell empties F first
   ```

   so when that `read` returned nothing, `F` was left as a single newline — and
   `jq -r` printing an empty string is exactly a 1-byte file, which is what the
   buffer synced to;
3. with the buffer and the disk agreeing on emptiness, the file was gone from
   both sides, and no `revert`/`clear`/proposal could bring it back.

What actually recovered it:

- the **harness's stored tool output** held a byte-exact snapshot of the file
  (454 lines) from an earlier `raj ctl read` — a copy nobody meant to make;
- `build/<name>/src/main.rs` held the *generated* code of the final file, so the
  re-application could be **proved** equivalent: rebuild, then diff the newly
  generated file against the preserved one, normalising only the
  `FILE:LINE:COL` strings that line numbers move. An empty diff ended the
  argument.

Two habits worth keeping:

- **Copy safely** — write beside the target, check it, then rename:

  ```bash
  raj ctl read --json "$F" | jq -r .text > "$F.new" &&
    test -s "$F.new" && grep -q '^server ' "$F.new" && mv "$F.new" "$F"
  ```

  `mv` cannot leave a truncated original, and a failed read cannot damage the
  target at all.
- **One writer per file.** `dev.sh` now refuses to start twice for the same
  reason; a background agent counts as a writer.

## 12. `claim` resolves a relative path against the agent's cwd, `edit` against the workspace root

**What happened.** With a shell sitting in `/tmp/rajwork`,
`raj ctl claim blender-mcp-comparison.md` reported
`claimed 1 file(s): /tmp/rajwork/blender-mcp-comparison.md`. One call later,
`raj ctl edit blender-mcp-comparison.md` — the same relative string — edited
`/work/blender-mcp-comparison.md` and worked. The mismatch surfaced only when the
*next* file was refused for not being in the claim set.

**Why it matters.** The claim set is the writers' mutual exclusion. If the name
that goes into it is not the name that gets written, the exclusion protects the
wrong path while reporting a path the user has never seen — and the failure reads
as a claim problem rather than a path problem.

**Suggested fix.** Resolve every path argument one way, against the workspace
root, and echo the resolved absolute path on `claim` so the two calls can be
compared by eye.

## 13. A claim outlives the identity that made it, and the warning never expires

**What happened.** Claiming `blender.rmcp.rb` printed
`also claimed by raj-e707e4fe` and `also claimed by raj-54a0595a` on every attempt.
Neither key appears in `who`, live or not: they are from sessions that have ended.
The writes were not blocked, only warned about.

**Why it matters.** The one message that should mean "stop, another agent is
writing this file" is permanently lit on any file with history, so it stops
carrying information exactly where it matters most — the file a second agent is
about to touch for real. Issue 11 is what a missing signal costs.

**Suggested fix.** Release a connection's claims when the connection goes away
(the editor already tracks `gone`), and separate the two cases in the wording:
*claimed by a live peer*, worth heeding, against *left over from an ended
session*, which the next claimant could take over with a note that it did.

## 14. A daemon restart drops unsaved buffers without warning

**What happened.** After a session with six buffers dirty, the editor's daemon
was restarted. Every buffer came back reported `saved`: the unsaved text was
gone, with no notice, no recovery file and no prompt on the way down. The two
files whose content existed only in a buffer — `blender.rmcp.rb` (the `remove`
tool, 15 lines) and `dev.sh` (the Python lint, 43 lines) — reverted to their
last saved state. Three docs that had already reached disk were unaffected.

**Why it matters.** Unsaved buffers are the point of the arrangement: an agent's
writes land there as proposals, the user reviews and saves. A restart that
silently discards them turns the review gate into a data-loss window, and it
does so exactly when the buffer holds the most work — the tail of a session. An
agent's edits are usually recoverable from its own scratch; the user's unsaved
typing is not.

**Suggested fix.** Persist unsaved buffers across a restart, or refuse to exit
while dirty buffers exist and say how many. Anything beats silence: one line
saying "3 buffers with unsaved changes discarded" would have turned a
reconstruction into a save.

**Recovery, for the record.** The agent re-proposed all three lost changes from
its sandbox copies, re-anchoring each by reading the current buffer first; all
landed in one pass. That works only when the agent kept a copy — nothing in the
editor offered one, and the change-set records from before the restart were gone
with the buffers.

## 15. LSP diagnostics can stay stale, and a question that was never answered looks like silence

Twice in one session the reading mattered and both times it was wrong in the same
way. Once it answered `{"status":"stale", "detail": "… does not describe the current
text"}`, and then nothing at all for three consecutive attempts. Once it answered
`ok` while the file its checker validates — an injected `.rs` read from disk — was
the *previous* save's copy, so a signature mismatch it had already caught for one
function went unreported for the next, and rustc found it instead.

The distinction a driver needs: **`ok` means the last publish had nothing to say
about the text it saw**, not that the current text is fine. When the checker reads a
second file, "the text it saw" can include that file as of before the save.

**Suggest:** fold the retry into the verb (`--wait` or `--until-fresh`), or report the
publish's age, so a caller can tell "clean" from "never asked". Failing that, make
`stale` an error rather than a status, since a driver that treats it as a reading is
the failure mode this entry is about.

## From the October session: three things that each cost a call

**An absolute workspace path is refused when the shell is elsewhere.** Running
`raj ctl read --as claude --json /work/smoke.sh | jq -r .text > /tmp/smoke/smoke.sh`
from `/tmp/smoke` answered `raj ctl: path is outside the workspace: /work/smoke.sh
is not under /tmp/smoke`. The path is absolute and inside the root map; only the
working directory was outside the mapped root, and that was enough to reinterpret
it against the cwd. The same read from `/work` worked unchanged. This is issue 12
seen from the other side, and it fails quietly: the redirect created `smoke.sh`
with nothing in it, `bash -n` said it parsed, and the suite reported no results
rather than an error.

**A literal search is refused when the pattern contains regex metacharacters.**
Looking for `let mut lit = [0.0f64; 3];` answered `search: no matches; "let mut
lit = [0.0f64; 3];" contains regex metacharacters — retry with --regex`. Search is
literal by default, so a literal `[` is not a regex and `--regex` would mean
something different. The message also leads with "no matches", so a caller that
pipes the result into `jq` gets `null` and a blank line: a structural check of mine
read as "zero occurrences" when it had not run at all.

**A workspace script cannot be run where the agent is.** `exec` is refused over TCP
by design and the sandbox shares no filesystem, so exercising `smoke.sh` meant
`raj ctl read --json <path> | jq -r .text > /tmp/copy` and running the copy. That is
workable, but every dependency has to be carried across by hand: `mcp.sh` needed a
shim that execs a node client of the same verbs, because the image has no curl. The
missing verb is the obvious one — say "materialise this file where I can run it" —
and until then the redirect above is that verb, done manually.

Still missing, and it cost a call on its own: **no way to ask whether a buffer is
backed by a file**. `buffers` reports `unsaved-changes` for a buffer whose file has
never been written, which is what `blender-tools/SKILL.md` was — a tab with 69 lines
and no file behind it. Issue 2's undefined `read --disk` is the verb that would
answer it.
