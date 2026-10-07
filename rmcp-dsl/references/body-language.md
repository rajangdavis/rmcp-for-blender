# Tool bodies

A body is `body do |a, b| ... end`. The block parameters must be field names of the tool's
`params`, each one must be read, and the last expression must be a String (or `result(:Name, ...)` when
the tool declares an `output:`). Before it, only
`name = expression` locals, guard clauses (`return "x" if cond`, `raise "msg" unless cond`) and
`progress(...)`, `hide_tool(...)` and `show_tool(...)` statements and `.each { ... }` loops are allowed. `return` ends the whole tool call with that string, even from inside a list block. Syntax available: `if`/`elsif`/`else` and `unless` (as a
value they need an `else`), `case x when "a", /re/ then ... else ... end` (strings, integers and
regexes), the ternary `c ? a : b`, `&&`, `||`, `!`, parentheses, string interpolation, and `rust(:name, args)` to call a declared function (`rust_fn`, `cmd_fn`,
`script_fn`). Bindings are called as `Module.method(args)` after `use_bindings :name`.

Integers: `:i32` and `:i64` arithmetic is overflow-checked, and `/` and `%` round down like Ruby.
`Rust::Int32(x)` and `Rust::Int64(x)` opt into Rust's truncating semantics for one operation.

Values that may be nil: `xs[i]`, `xs.first`, `xs.last`, `s.index(x)` and `s =~ /re/` return nil in Ruby
when nothing matches, so a body may only use them through `|| default` (the default runs only when the
value is nil, and `|| raise("message")` is allowed), `.nil?` or `.to_s`. Anything else is refused, and
so is putting one inside a string interpolation without a default. A field declared `optional: true`
is nil-able the same way (`limit || 10`); an optional nested object is read with `&.` (`address&.city`,
nil when the object is absent), and `first`, `last`, `[]` and `find` on a list of objects give a nil-able
element, read the same way. The `=~` operator takes a regex literal and gives the
character index of the first match (not a boolean): `(text =~ /\d/) || -1`.

`s.to_i` reads the leading integer like Ruby does (spaces, a sign, digits with single underscores
between them, stopping at anything else, no digits is 0) but returns an i64: a value that does not
fit is an error result, because Ruby would return a bignum.

Strings: `s[start, length]` and `s[i]` count characters, take negative positions, and are nil when
out of range (so they are nil-able, see above). `s * n` repeats; a negative count is an error
result. `Integer(text, 10)` parses strictly (surrounding spaces, a sign and single underscores
between digits are fine, anything else is an error result); the base 10 must be written out.

`gsub` and `sub` with a block take a regex literal; the block receives the matched text and returns the
replacement (`text.gsub(/\d+/) { |m| "[#{m}]" }`). Unlike list blocks, they cannot contain
`raise`, `to_i` or integer arithmetic yet (they compile to Rust closures).

List blocks (`map`, `each`, `select`, `reject`, `find`, `any?`, `all?`, `count`) take one plain parameter; on
a `list(:Address)` the parameter is an object (`o.city`). `map`
returns strings, integers or floats and the others must end in true or false. They may use integer
arithmetic, `to_i` and `raise`. `n.times`, ranges and `upto`/`downto` make lists of integers, so
`n.times.map { |i| i * i }.join(",")` works.
Maps take blocks too: `m.map { |k, v| ... }` gives a list of strings or integers (the result of the
block), while `m.select { |k, v| ... }` and `m.reject { |k, v| ... }` give a new map with the same key
and value types. A map block takes exactly `|k, v|` (`k` the String key, `v` the value), both must be
read, and a map is read-only: in-place changes are not supported.
`each` runs a block for its effects on a list (`xs.each { |x| ... }`) or a map (`m.each { |k, v| ... }`):
the block's value is ignored, so it may `raise`, `return`, call `progress` or call a helper, and the list
or map itself is the value (Ruby's `each` returns its receiver).

Helpers: `helper :name, args: [:string, :i64], returns: :string do |text, n| ... end` declares a function
that tool bodies and later helpers call by name: `name(text, 3)`. Argument and result types are always
written out: `:string`, `:i32`, `:i64`, `:f64`, `:bool`, `:string_list`, `:i64_list`, `:f64_list`, and a trailing ?
makes a parameter or result nil-able (`:string?`, `:i64?`, `:string_list?`, ...). A helper may also take
keyword parameters: `kw: { sep: [:string, false] }` with `do |text, sep: "-"| ... end`, called as
`name(text, sep: ",")`; a nil-able declared type or a `nil` default makes the parameter nil-able in the
body. A helper may only call helpers declared above it, so there is no recursion. It may use `return`,
`raise` and checked arithmetic; a failure becomes an error result in the caller. A helper must be called
somewhere. Sorbet cannot know names declared in the DSL, so run `rmcp_dsl rbi FILE...` to write their
signatures to `sorbet/rbi/rmcp_dsl/dsl_helpers.rbi` and keep the file `# typed: true`; the compiler
checks every call regardless.

Async: a `rust_fn` (or a binding function) declared with `async: true` is an `async fn`, and a body
that calls any async function is compiled `async fn` too (`async: true` is inferred, so callers need
not say it). A declaration's `returns:` is the eventual value, not a future, and a call site is
awaited, with `?` when the callee can fail. An async call is allowed in a tool body, a helper, a
prompt body or a resource body; a `gsub`/`sub` block and a Ruby-compiled binding have no async
context, so an async call there is refused. An async recursive helper cycle is refused (it would
need `Box::pin`), and `async: true` on `cmd_fn`/`script_fn` is refused because a subprocess blocks.

Errors: `raise "message"` (or `raise some_string`) ends the call with an MCP error result,
`isError: true`, carrying the message. It has no value, so use it where any type fits, for
example `cond ? raise("bad") : value` or in one branch of an `if`. A body cannot end in a bare
`raise` or `return`. Integer overflow and division by zero also
return error results.

The request context: a tool body may read the MCP call it is answering with `client_name` and
`client_version` (the calling client, nil-able), `protocol_version` (nil-able), `request_id` (a String),
`progress_token` (nil-able) and `cancelled?` (a bool). They take no arguments and are available only in a
tool body; the nil-able ones follow the usual `|| default`, `.nil?` and `.to_s` rules. A tool body may
also send progress with `progress(value)` or `progress(value, total: n, message: "s")` on a line of its
own: it is a statement, not a value, so it cannot be assigned or returned, and it sends
`notifications/progress` only when the client supplied a progress token. Such a tool is compiled async.

Cancellation is cooperative: on `notifications/cancelled` the request's token is cancelled, but the
body keeps running until it checks `cancelled?`. A loop that awaits inside, such as one sending
`progress(...)` each iteration, can stop itself with `raise "cancelled" if cancelled?`; blocking work
(a `cmd_fn` or `script_fn` call, or a binding that blocks) is not interrupted.      `notifications/progress` only when the client supplied a progress token. Such a tool is compiled async.

A tool body may also ask the client for input with `elicit(message, schema: { ... })`: `message` is a










string expression and `schema:` is a JSON object literal whose properties are primitive (string, number,
integer, boolean or enum). The call is a server-to-client request, so the tool is compiled async and can
fail. Its value has two fields: `answer.action` is `"accept"`, `"decline"` or `"cancel"`, and
`answer.content` is the JSON value the client sent back, nil when it sent none (use `|| default`, `.nil?`
or `.to_s`).

A tool body may also send a log message with `log(:info, "text")` on a line of its own, but only when
the server declares `feature :logging` (the level is one of :debug, :info, :notice, :warning, :error,
:critical, :alert, :emergency; the message is a string expression). It is a statement, not a value,
sends `notifications/message`, and makes the tool compiled async. Logging is deprecated by SEP-2577 in
rmcp: the declaration is what advertises the capability and answers `logging/setLevel`, and the emitted
call is scoped with `#[allow(deprecated)]` so the generated crate stays warning-free.

A tool body may also read the client roots with `roots()`, but only when the server declares
`feature :roots` (roots is deprecated by SEP-2577 in rmcp, so the emitted `roots/list` call is scoped
with `#[allow(deprecated)]`). `roots()` is a server-to-client request: the tool is compiled async and
can fail, and a client that did not declare the capability makes the call an error result. Its value is
a list of roots; `roots().map { |root| ... }` builds a list of strings or integers, `roots().each do
|root| ... end` runs the block for its effects, and `roots().length` / `roots().empty?` read the list.
Inside the block, `root.uri` is a String and `root.name` is nil-able (use `|| default`, `.nil?` or
`.to_s`).

A tool body may also ask the client's LLM for a completion with
`sample(prompt, max_tokens: n, system: "s", temperature: 0.5, stop: ["STOP"])`, but only when the
server declares `feature :sampling`. `prompt` is a string and `max_tokens:` (an integer) is required;
`system:`, `temperature:` and `stop:` (a list of strings) are optional and map to the rmcp builders.
It is a value, not a statement: the call is a server-to-client request, so the tool is compiled async
and can fail, and a client that did not declare the sampling capability makes the call an error result.
Its value has `text` (the assistant's text, nil-able when the reply carried no text), `model`, `role`
and nil-able `stop_reason`. Sampling is deprecated by SEP-2577 in rmcp, so the emitted
`sampling/createMessage` call is scoped with `#[allow(deprecated)]`. The message history and non-text
content are not exposed yet.


## Methods

Allowed: `+`, `-`, `*`, `/`, `%`, `==`, `!=`, `<`, `<=`, `>`, `>=`, `!`, `-@`, `to_s`, `upcase`, `downcase`, `strip`, `gsub`, `sub`, `split`, `length`, `size`, `capitalize`, `map`, `join`, `start_with?`, `end_with?`, `include?`, `empty?`, `match?`, `reverse`, `first`, `last`, `[]`, `index`, `tr`, `delete`, `squeeze`, `to_i`, `each`, `select`, `reject`, `find`, `any?`, `all?`, `count`, `sort`, `uniq`, `partition`, `chars`, `lines`, `times`, `upto`, `downto`, `sum`, `min`, `max`, `to_a`, `fetch`, `key?`, `has_key?`, `member?`, `keys`, `values`, `merge`, `tally`, `=~`, `client_name`, `client_version`, `protocol_version`, `request_id`, `progress_token`, `cancelled?`, plus `rust(:name, args)` for a declared function.

String methods in detail:

- `String#strip`: Ruby strips NUL, \t \n \v \f \r and space. NBSP (U+00A0) is NOT stripped. Prints W-STR-STRIP-RUBY (warning).
- `String#downcase`
- `String#length`: Ruby counts characters. Emitted Rust must use chars().count(), not len().
- `String#gsub(string, string)`: Literal replacement of every occurrence: Rust str::replace.
- `String#sub(string, string)`: Literal replacement of the first occurrence: Rust str::replacen(.., 1).
- `String#gsub(regex, string)`: pat is Ruby regex source; the Rust side gets RegexTranslate output. \d is ASCII-only in Ruby.
- `String#sub(regex, string)`: First match only.
- `String#split.length`: Ruby awk-style split. Rust: split on the explicit set, drop empty pieces, count.
- `String#capitalize`: Prints W-STR-CAPITALIZE (warning).
- `String#start_with?`
- `String#end_with?`
- `String#include?`
- `String#empty?`
- `String#match?(regex)`: Ruby ^ and $ are line anchors; \d is ASCII-only. Both are handled by RegexTranslate.
- `String#reverse`
- `String#index(string)`: Character offset of the first match, or nil. Ruby counts characters, so the Rust maps the byte offset back.
- `String#split(string).length`
- `String#split(string).first`
- `String#split(string).last`
- `String#tr`
- `String#delete`
- `String#squeeze`: With no argument, every run of the same character becomes one.
- `String#to_i`: Leading whitespace, optional sign, digits with single underscores between them; stops at anything else; no digits is 0. The result is an i64 and a value that does not fit is an error result.
- `String#split(string, int).length`
- `String#split(string, int).last`
- `String#partition(string).first`
- `String#partition(string).last`
- `String#lines.length`
- `String#[](int, int)`
- `String#[](int)`
- `String#*`
- `String#gsub(regex) { bracket }`
- `String#sub(regex) { bracket }`
- `String#gsub(regex) { upcase }`

## Notifications

Notifications never change the generated code or fail a build; the environment only decides what
is printed. Set `RMCP_DSL_WARN` or `RMCP_DSL_NOTICE` to `all`, `none` or a comma-separated list
of codes, or pass `--warn SPEC` and `--notice SPEC`. An unknown code is an error.

- `W-STR-STRIP-RUBY` (warning)
- `N-STR-STRIP-RUST` (notice)
- `W-STR-CAPITALIZE` (warning)
- `N-RUST-INJECTED` (notice)
- `W-RUST-FN-MISSING` (warning)
- `N-EXEC-INJECTED` (notice)
- `N-BINDING` (notice)
- `N-OPENAPI` (notice)
- `W-OPENAPI-AUTH` (warning)
- `N-DEPRECATED-FEATURE` (notice)

## Not supported yet

These are refused today; the compiler's message is the authority if this list is out of date.

- Lists of strings and lists of integers: `split` (no argument, a plain separator, or a separator
  with an integer-literal limit), `partition`, `chars`, `lines`, `n.times`, `a.upto(b)`,
  `a.downto(b)`, ranges `(a..b)` and `(a...b)`, array literals, and `map`, `join`, `length`, `size`,
  `first`, `last`, `[]`, `empty?`, `include?`, `select`, `reject`, `find`, `any?`, `all?`, `count`,
  `sort`, `uniq`, `reverse`, `to_a`; on integer and float lists also `sum`, `min` and `max`. Not supported:
  in-place map changes, and `split` with a regex or a variable limit. A `list(:Address)` (a list of nested
  objects) supports `length`, `size`, `empty?`, `first`, `last`, `[]`, `each`, `map`, `select`, `reject`,
  `find`, `any?`, `all?`, `count` and `reverse`; `sort`, `uniq`, `include?`, `join`, `sum`, `min` and `max`
  are refused, because an object has no ordering, equality or string form.
- `gsub`/`sub` with a block whose pattern is a string or that reads capture
  groups (`$1`, `$~`), string ranges (`s[1..2]`; write `s[1, 2]`),
  `Integer(text)` without the base, and `tr` or `delete` with ranges (`a-z`) or `^`.
- `while`/`for` loops and `def` inside a body.
- Regex literals are only accepted by `gsub`, `sub`, `match?`, `=~` and `when`.

Predicates and extraction are often expressible anyway: `s.sub(/\Ahttp/, "") != s` tests a prefix,
and two `sub` calls with lazy, dot-all patterns (`/\A.*?<title[^>]*>/mi`) cut text out between tags.
