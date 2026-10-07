# raj editor issues found driving it from an agent session

Context: an agent in a container driving `raj ctl` over TCP against an editor on
the user's machine, editing one DSL file and building it with a compiler that
reads **disk**. Ordered by how much each one cost.

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

## 3. Stale generated-file buffers shadow reads, and `save --all` clobbers generated output

`build/**/src/main.rs` and `src/blender_bridge.rs` were left as headless buffers
from earlier reads. After a later build rewrote them, the buffers kept the
pre-build text and reported `unsaved-changes`, and `read`/`search` answered from
the buffer. The agent read a look-tool body that no longer existed and nearly
filed a codegen bug that wasn't there.

`reload` and `close --discard` are both refused:
`main.rs holds unsaved text written by the user; reload and close --discard may
drop only the caller's own unsaved text` — even though the agent never wrote a
byte of that file.

Sharper half: a `save --all` in that workspace writes the stale buffers back
over freshly generated sources.

**Suggest:** don't keep generated paths as buffers (or reload them on change),
and let a driver refresh text it never wrote.

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

## 6. Rejected zero-width change sets deadlock `clear` and keep the workspace not-ready

Two rejected sets — one 0 bytes, one 19 bytes, both `moved` — could not be
disposed of:

```
clear: change set 47 cannot be cleared: change set 48 (author 19, bytes 0..0)
overlaps it; reject or clear that set first
```

and 48 is blocked by the agent's own later set, whose purge would *reverse* a
good edit. So `status` stays `dirty: 1 rejected sets (clear to dispose)` and
`not ready: 3 of 14 buffer(s) dirty or pending` indefinitely, and the "clear to
dispose" hint names an action that is refused.

**Suggest:** let a zero-width set be cleared without a neighbour's consent (it
carries no text), or offer a "drop every rejected/invalid set" that resolves the
chain in one step.

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

## 10. `exec` over TCP plus an unmounted sandbox leaves the agent unable to verify anything

`exec` is refused over TCP by design ("the command would run on the editor's
machine, outside your sandbox — run it with your own shell instead"), and the
skill's answer is that the sandbox has the workspace mounted. Here the sandbox
had no mount (an empty working directory) and no toolchain, so every build, test
and diff was a user round trip — about a dozen of them in one session.

**Suggest:** state plainly, in the container section, that without the
`-v "$PWD:/workspace"` mount the agent can write code but can never build it, so
every verification is the user's; that is a property of the setup, and knowing it
up front would have shaped the whole session (the user offered exactly this
mid-way, as "hooks").

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

