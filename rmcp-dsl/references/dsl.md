# DSL reference

A file holds exactly one top-level `server` call. Inside it go declarations; the examples put
`params` before the tools that use them. Names are symbols or string literals as listed below;
anything else is refused. A `field` takes `description:`, `optional: true` (the value is nil-able in
the body), `default:` (the field is then always present), and JSON schema constraints that the generated
server also enforces: `min:` and `max:` on numbers, `exclusive_min:` and `exclusive_max:` (which the value
must be above and below), `multiple_of:` (a positive integer the value must be a multiple of, for the
integer types), `min_length:`, `max_length:`, `pattern:` (a Rust regex) and `enum:` on strings,
`min_items:` and `max_items:` on lists. A field is a scalar, a list
(`:string_list`, `:i64_list`, `:f64_list`, or `list(:Address)` for a list of objects) or another `params`
declared above it (a nested object, read as `address.city`, or `address&.city` when the field is
`optional: true`); `format:` (`:email`, `:uri`, ...) is advice to the client. A `tool`
takes `title:` and the annotations `read_only:`, `destructive:`, `idempotent:` and `open_world:`,
which tell a client whether the tool is safe to call without asking. A `prompt` has the same shape as a tool and returns
one user message, as text or content blocks; MCP passes prompt arguments as strings, so its params may only have :string
fields. A tool may declare a structured result: `output :Name do field ... end` (fields take only
`description:` and `optional:`), and `tool ..., output: :Name`. The body then ends in
`result(:Name, field: value, ...)`, giving every field once; clients get typed JSON and an output schema.
JSON-shaped values are basic typed Ruby types: a field may be a typed map with string keys and one value
type, `map(:i64)`, `map(:string)`, `map(:f64)`, `map(:bool)`, `map(list(:string))`, a map of a params object
(`map(:Address)`) or a nested map (`map(map(:i64))`) (and `list(:string)` is `:string_list`). A body reads
one with `m["k"]` (nil-able: `|| default`; on a map of objects read fields with `&.`, and `m["a"]["b"]`
indexes a map of maps), `fetch`, `key?`, `keys`, `values` (a list of objects or maps when the value is one),
`size`, `empty?` and `merge`, builds one with `{ "a" => 1 }` (string keys, values of one type) or
`items.tally`, and keys come back sorted (a Rust BTreeMap). Nothing changes a map in place. More complicated
JSON belongs in a binding: it declares a type with `class Value < RmcpDsl::Opaque; type_rust "serde_json::Value", wire: true; end`,
the DSL holds values of it, passes them to that binding's functions and, with `wire: true`, takes them as `field :doc, Json::Value`.
`meta:` on a tool, prompt or resource is static metadata sent as `_meta`, a JSON
object literal such as `{ "com.example/tier" => "free" }` with MCP-valid keys (reverse-DNS prefix; reserved
prefixes and `progressToken` are refused). A tool body or a prompt message may end in content blocks instead of a string: `text(s)`,
`image(base64, "image/png")`, `audio(base64, "audio/wav")`, `resource_link(uri, name: ..., size: ...)`,
`embedded_text(uri, text, mime_type: ...)` and `embedded_blob(uri, base64)`, one or an array of them, each with
optional `audience:` and `priority:`; literal base64, MIME types and URIs are checked at compile time.
`task: true` on a tool lets a client that declared the tasks extension poll for the result (`task_ttl_ms:` and
`task_poll_ms:` tune it). `updates: ["notes://notes/{id}"]` on a tool tells subscribed clients the resource
changed once the tool succeeds ({field} is filled from the params), and `resource_list_changed: true` tells
them the list of resources changed. A resource `size:` is its size in bytes (checked when the body is a plain
string). A resource template may use `{+path}` (slashes allowed), `{a,b}` (several values), `{x*}` (a
:string_list field) and `{?q,limit}` (optional :string fields, nil when absent). `page_size: 10` on the server
pages tools, prompts, resources and templates, with opaque cursors. `setting :token, env: "API_TOKEN", secret: true`
declares a value read from the environment at startup (`default:`, `optional:`); a body reads it with
`setting(:token)`, and a secret can only be passed to a binding or rust_fn function (never printed, returned or
compared). `input_schema: { ... }` on a tool publishes a hand-written schema, checked against the fields.
A prompt can be a conversation:
use `message :assistant do ... end` and `message :user do |topic| ... end` blocks, in order, instead of
one `body`. A prompt argument is completed automatically: an `enum:` field offers its values, a `:string` field
may name a helper with `complete: :helper` (one `:string` argument, returning `:string_list`), and a
`complete do |arg, typed| ... end` block answers for every argument at once (the values that start with what
was typed). A resource whose `uri:` has `{placeholders}` (plain {name}, RFC 6570 level 1) is a template: give
it `params:` with a :string field per placeholder (its arguments are completed too, by `enum:`/`complete:` or a
`complete` block); the body takes those values, and a `raise` means the
resource does not exist. The server takes `title:`, `description:`, `website_url:` and `icon:` (an http, https or
data: URI), and tools, prompts and resources take `icon:`. A resource also takes `audience:` (`["user"]`,
`["assistant"]` or both) and `priority:` (0 to 1). `transport :stdio` serves over standard input and
output; `transport :http, port: 8080` serves streamable HTTP at `/mcp` on 127.0.0.1 with rmcp's default
sessions and host check. A `resource` is readable content at a `uri:` ("scheme://path") whose body takes no
parameters and runs on every read: a plain string is one text content, and `text(s)` or `blob(base64)` (each
with optional `uri:`, default the uri read, and `mime_type:`, default the resource's) build resource contents,
alone or as an array. `instructions:` on the server tells a model how to use it. The declarations are generated from the compiler's
signature table, so this page matches the installed version.

## Types

- `:i32` is Rust `i32`
- `:i64` is Rust `i64`
- `:f64` is Rust `f64`
- `:bool` is Rust `bool`
- `:string` is Rust `String`

## Declarations

### `server`

The one top-level call: names the server and holds everything it offers; needs a version and a transport.

- Allowed inside: the top level of the file
- Positional arguments: `name` (string literal)
- Keyword arguments: `version:` (string literal, required), `instructions:` (string literal, optional), `title:` (string literal, optional), `description:` (string literal, optional), `website_url:` (string literal, optional), `icon:` (string literal, optional), `page_size:` (non-negative integer literal, optional)
  - `version:` The server's version as semver such as 0.1.0, reported to clients.
  - `instructions:` Text that tells a model how to use this server as a whole.
  - `title:` A human-readable name that clients may show instead of the server name.
  - `description:` A short description of what the server does.
  - `website_url:` An http or https address of a page about the server.
  - `icon:` An icon for the server: an http or https address, or a data: URI.
  - `page_size:` How many tools, prompts, resources or templates one page of a list holds; clients follow nextCursor for the rest.
- Takes a block of DSL declarations

### `params`

A struct of arguments (fields) for a tool, a prompt or a resource template; every params must be used.

- Allowed inside: `server`
- Positional arguments: `name` (CamelCase symbol)
- Keyword arguments: none
- Takes a block of DSL declarations

### `output`

A structured result a tool may return; its fields are typed and the client gets JSON and an output schema.

- Allowed inside: `server`
- Positional arguments: `name` (CamelCase symbol)
- Keyword arguments: none
- Takes a block of DSL declarations

### `field`

One field of a params or output struct, with a snake_case name and a type symbol such as :string or :i32.

- Allowed inside: `params` or `output`
- Positional arguments: `name` (snake_case symbol), `type` (a type symbol (:i32, :i64, :f64, :bool, :string, :string_list, :i64_list, :f64_list, or the CamelCase name of another params to nest an object))
- Keyword arguments: `description:` (string literal, optional), `optional:` (true or false, optional), `default:` (a string, number or true/false literal, optional), `min:` (number literal, optional), `max:` (number literal, optional), `exclusive_min:` (number literal, optional), `exclusive_max:` (number literal, optional), `multiple_of:` (number literal, optional), `min_length:` (non-negative integer literal, optional), `max_length:` (non-negative integer literal, optional), `pattern:` (string literal, optional), `enum:` (array of string literals, optional), `format:` (one of :uri, :email, :date_time, :date, :uuid, :hostname, :ipv4, :ipv6, optional), `min_items:` (non-negative integer literal, optional), `max_items:` (non-negative integer literal, optional), `complete:` (snake_case symbol, optional)
  - `description:` What the field means; it is part of the schema the model reads, so say what a valid value is.
  - `optional:` When true the caller may leave the field out and the body sees nil; it cannot be combined with `default:`.
  - `default:` The value used when the caller omits the field, so the body always has one; it must pass the field's other limits.
  - `min:` The smallest allowed number; only for :i32, :i64 and :f64 fields, and an integer for the integer types.
  - `max:` The largest allowed number; only for :i32, :i64 and :f64 fields, and not below `min:`.
  - `exclusive_min:` The smallest allowed number, which the value must be above; only for :i32, :i64 and :f64 fields, and an integer for the integer types.
  - `exclusive_max:` The largest allowed number, which the value must be below; only for :i32, :i64 and :f64 fields, and an integer for the integer types.
  - `multiple_of:` The value must be a multiple of this positive integer; only for :i32 and :i64 fields.
  - `min_length:` The fewest characters a :string field may have; the generated server enforces it.
  - `max_length:` The most characters a :string field may have; not below `min_length:`.
  - `pattern:` A Rust regex that a :string value must match; the generated server enforces it.
  - `enum:` The only strings a :string field accepts: a non-empty list of distinct values, also offered as prompt completions.
  - `format:` A JSON schema format hint for a :string field, such as :email or :uri; it is advice to the client, not checked.
  - `min_items:` The fewest items a list field (:string_list, :i64_list or :f64_list, or list(:Name)) may have.
  - `max_items:` The most items a list field (:string_list, :i64_list or :f64_list, or list(:Name)) may have; not below `min_items:`.
  - `complete:` Names a helper that offers completion values for this :string prompt or template argument, instead of `enum:`.
- Takes no block

### `tool`

A tool: a function the model can call. Its body returns the result text (or a `result(...)` for an output).

- Allowed inside: `server`
- Positional arguments: `name` (snake_case symbol)
- Keyword arguments: `params:` (CamelCase symbol, required), `description:` (string literal, required), `title:` (string literal, optional), `read_only:` (true or false, optional), `destructive:` (true or false, optional), `idempotent:` (true or false, optional), `open_world:` (true or false, optional), `output:` (CamelCase symbol, optional), `icon:` (string literal, optional), `meta:` (a JSON object literal with string keys (`{ "example.com/tier" => "free" }`), optional), `input_schema:` (a JSON Schema object literal with string keys (`{ "type" => "object", "properties" => { ... } }`), optional), `task:` (true or false, optional), `task_ttl_ms:` (non-negative integer literal, optional), `task_poll_ms:` (non-negative integer literal, optional), `updates:` (array of string literals, optional), `resource_list_changed:` (true or false, optional)
  - `params:` The params struct, declared above, that gives the tool its arguments.
  - `description:` What the tool does; the model reads it to decide when to call the tool.
  - `title:` A human-readable name that clients may show instead of the tool name.
  - `read_only:` Tells a client the tool does not change anything, so it is safe to call without asking.
  - `destructive:` Tells a client the tool may delete or overwrite things, so it may ask first; only meaningful when `read_only:` is false.
  - `idempotent:` Tells a client that calling the tool again with the same arguments has no further effect; only meaningful when `read_only:` is false.
  - `open_world:` Tells a client the tool reaches outside systems such as the web, so its results can vary and are untrusted.
  - `output:` The output struct, declared above, that the tool returns; the body then ends in `result(:Name, ...)`.
  - `icon:` An icon for the tool: an http or https address, or a data: URI.
  - `meta:` Static metadata clients may read, a JSON object literal sent as `_meta`; keys follow the MCP rules (reverse-DNS prefix such as com.example/).
  - `input_schema:` A JSON Schema object literal that replaces the schema made from the fields; its properties and required list are checked against them.
  - `task:` Lets a client that declared the tasks extension poll for the result as a task; every other client still gets it directly.
  - `task_ttl_ms:` How long, in milliseconds, a finished task stays available (the extension's ttlMs; default 300000). Needs task: true.
  - `task_poll_ms:` The polling interval clients are asked to use, in milliseconds (pollIntervalMs; default 1000). Needs task: true.
  - `updates:` Resource uris this tool changes, so subscribed clients are told once it succeeds; {field} fills from the params.
  - `resource_list_changed:` True when the tool adds or removes resources; clients that asked are told the resource list changed.
- Takes a block of DSL declarations

### `helper`

A typed function that tool bodies and later helpers can call by name; it must be called somewhere.

- Allowed inside: `server`
- Positional arguments: `name` (snake_case symbol)
- Keyword arguments: `args:` (htypes, required), `returns:` (one of :string, :i32, :i64, :f64, :bool, :string_list, :i64_list, :f64_list, :string?, :i32?, :i64?, :f64?, :bool?, :string_list?, :i64_list?, :f64_list?, required), `kw:` (helper_kw, optional), `async:` (true or false, optional)
  - `args:` The argument types in order, such as [:string, :i64]; write them out, and use a trailing ? such as :string? for a nil-able parameter.
  - `returns:` The result type; a trailing ? as in :string? means the helper may return nil.
  - `kw:` Keyword parameters a helper takes: a hash of `name: [type, required]`, declared after the positional ones and passed by name at the call site.
  - `async:` Not supported: async is inferred from the body, so `async: true` on helper is refused.
- Takes a block of restricted Ruby

### `prompt`

A prompt: a template that returns one user message, as text or content blocks, or a conversation of `message` blocks.

- Allowed inside: `server`
- Positional arguments: `name` (snake_case symbol)
- Keyword arguments: `params:` (CamelCase symbol, required), `description:` (string literal, required), `title:` (string literal, optional), `icon:` (string literal, optional), `meta:` (a JSON object literal with string keys (`{ "example.com/tier" => "free" }`), optional)
  - `params:` The params struct, declared above, that gives the prompt its arguments; every field must be :string.
  - `description:` What the prompt is for; a client shows it when listing prompts.
  - `title:` A human-readable name that clients may show instead of the prompt name.
  - `icon:` An icon for the prompt: an http or https address, or a data: URI.
  - `meta:` Static metadata clients may read, a JSON object literal sent as `_meta`; keys follow the MCP rules (reverse-DNS prefix such as com.example/).
- Takes a block of DSL declarations

### `resource`

A resource: text a client can read at a URI; a URI with {placeholders} makes it a template.

- Allowed inside: `server`
- Positional arguments: `name` (snake_case symbol)
- Keyword arguments: `uri:` (string literal, required), `description:` (string literal, optional), `mime_type:` (string literal, optional), `title:` (string literal, optional), `icon:` (string literal, optional), `audience:` (array of string literals, optional), `priority:` (number literal, optional), `params:` (CamelCase symbol, optional), `meta:` (a JSON object literal with string keys (`{ "example.com/tier" => "free" }`), optional), `size:` (non-negative integer literal, optional)
  - `uri:` The address clients read, written scheme://path; {name} placeholders make a template and need `params:`.
  - `description:` What the resource contains; a client shows it when listing resources.
  - `mime_type:` The media type of the text, such as text/markdown or text/plain.
  - `title:` A human-readable name that clients may show instead of the resource name.
  - `icon:` An icon for the resource: an http or https address, or a data: URI.
  - `audience:` Who the resource is for: a non-empty list of distinct values from "user" and "assistant".
  - `priority:` How important the resource is, from 0 (least) to 1 (most), as an integer or a float.
  - `params:` The params struct with one :string field per {placeholder} in `uri:`; only for a template.
  - `meta:` Static metadata clients may read, a JSON object literal sent as `_meta`; keys follow the MCP rules (reverse-DNS prefix such as com.example/).
  - `size:` The size of the content in bytes, shown to clients; checked against the body when that is a plain string.
- Takes a block of DSL declarations

### `body`

The Ruby-subset code that computes the result of a tool, a prompt message or a resource.

- Allowed inside: `tool` or `prompt` or `resource`
- Positional arguments: none
- Keyword arguments: none
- Takes a block of restricted Ruby

### `message`

One message of a prompt conversation, sent as the user or the assistant; use it instead of one `body`.

- Allowed inside: `prompt`
- Positional arguments: `role` (one of :user, :assistant)
- Keyword arguments: none
- Takes a block of restricted Ruby

### `complete`

A block that answers completions for a prompt's or resource template's arguments; it gets the argument name and the text typed so far.

- Allowed inside: `prompt` or `resource`
- Positional arguments: none
- Keyword arguments: none
- Takes a block of restricted Ruby

### `transport`

How the server talks to a client: standard input and output (:stdio) or streamable HTTP (:http).

- Allowed inside: `server`
- Positional arguments: `kind` (one of :stdio, :http)
- Keyword arguments: `port:` (non-negative integer literal, optional), `auth_setting:` (snake_case symbol, optional), `oauth_issuer:` (snake_case symbol, optional), `oauth_audience:` (snake_case symbol, optional), `oauth_resource:` (snake_case symbol, optional)
  - `port:` The TCP port, 0 to 65535, that `transport :http` listens on at 127.0.0.1; required for :http, refused for :stdio.
  - `auth_setting:` The secret setting every request to /mcp must carry as `Authorization: Bearer ...`, or get a 401; only for :http.
  - `oauth_issuer:` The setting holding the OAuth issuer URL; every request to /mcp must carry a JWT that issuer signed (RS256 or ES256); only for :http.
  - `oauth_audience:` The setting holding the audience (`aud`) a token must have been issued for; required with `oauth_issuer:`.
  - `oauth_resource:` The setting holding this server's public base URL for the protected-resource metadata; without it, http://127.0.0.1 and the port.
- Takes no block

### `feature`

Declares a backend feature the server uses, such as `:logging`; a gated body built-in needs it and it advertises the capability.

- Allowed inside: `server`
- Positional arguments: `name` (one of :logging, :sampling, :roots, :elicitation, :progress)
- Keyword arguments: none
- Takes no block

### `rust_crate`

Adds a Cargo dependency (a crate name and a version) to the generated server for injected Rust.

- Allowed inside: `server`
- Positional arguments: `crate` (string literal), `version` (string literal)
- Keyword arguments: none
- Takes no block

### `rust_item`

Injects Rust source text into the generated crate unchecked; the compiler prints a notice for it.

- Allowed inside: `server`
- Positional arguments: `code` (string literal)
- Keyword arguments: none
- Takes no block

### `rust_fn`

Declares the argument and result types of a Rust function so bodies can call it as `rust(:name, ...)`.

- Allowed inside: `server`
- Positional arguments: `name` (snake_case symbol)
- Keyword arguments: `args:` (array of type symbols, required), `returns:` (one of :i32, :i64, :f64, :bool, :string, required), `from:` (snake_case symbol, optional), `async:` (true or false, optional)
  - `args:` The argument types in order, such as [:string, :i32].
  - `returns:` The result type of the Rust function.
  - `from:` The `as:` name of the rust_file module that holds the function; leave it out for a function from rust_item.
  - `async:` True when the Rust function is async; a body that calls it awaits the eventual value.
- Takes no block

### `use_bindings`

Loads bindings/NAME.rb, found next to the DSL file, so bodies can call its typed functions as Module.method.

- Allowed inside: `server`
- Positional arguments: `name` (snake_case symbol)
- Keyword arguments: none
- Takes no block

### `setting`

A value the server reads from an environment variable when it starts, such as an API address or key; bodies read it with setting(:name).

- Allowed inside: `server`
- Positional arguments: `name` (snake_case symbol)
- Keyword arguments: `env:` (string literal, required), `description:` (string literal, optional), `default:` (string literal, optional), `optional:` (true or false, optional), `secret:` (true or false, optional)
  - `env:` The environment variable the value is read from; the server refuses to start when a required one is missing or empty.
  - `description:` What the value is for, shown in the message when the server cannot start without it.
  - `default:` The value used when the environment variable is not set, which makes the setting not required.
  - `optional:` True when the server can run without the value; the body then gets a string or nil.
  - `secret:` True for a key or token: a body can only pass it to a binding or rust_fn function, never print or return it.
- Takes no block

### `openapi`

Makes one tool per operation of an OpenAPI 3.0 or 3.1 file beside this one, calling the API it describes; checked when compiled.

- Allowed inside: `server`
- Positional arguments: `file` (string literal)
- Keyword arguments: `base_url:` (snake_case symbol, optional), `auth_setting:` (snake_case symbol, optional), `auth_header:` (string literal, optional), `auth_scheme:` (string literal, optional), `include_tags:` (array of string literals, optional), `exclude:` (array of string literals, optional)
  - `base_url:` The setting that holds the API's address; without it the first server address of the document is used.
  - `auth_setting:` The setting whose value is sent with every request, as a bearer token unless auth_header: or auth_scheme: says otherwise.
  - `auth_header:` The header that carries the auth_setting value (default Authorization).
  - `auth_scheme:` A word before the value in the auth header, such as Bearer (default Bearer for Authorization, none for other headers).
  - `include_tags:` Only the operations that have at least one of these tags become tools.
  - `exclude:` Operations to leave out, by operationId (or by the tool name made from the method and path).
- Takes no block

### `rust_file`

Copies a hand-written .rs file from beside the DSL file into the crate as a module that rust_fn can point at.

- Allowed inside: `server`
- Positional arguments: `path` (string literal)
- Keyword arguments: `as:` (snake_case symbol, required), `uses:` (one of :subprocess, optional)
  - `as:` The module name the file gets in the crate, and the name `from:` refers to; it cannot be main or tests.
  - `uses:` Set to :subprocess when the module starts subprocesses, so the generated crate includes the subprocess helper.
- Takes no block

### `cmd_fn`

A function that runs a subprocess with fixed arguments and returns its output as a string; no shell is used.

- Allowed inside: `server`
- Positional arguments: `name` (snake_case symbol)
- Keyword arguments: `program:` (string literal, required), `argv:` (array of string literals, optional), `args:` (array of type symbols, required), `returns:` (one of :string, required), `pass:` (one of :argv, :stdin, optional), `async:` (true or false, optional)
  - `program:` The program to run, such as tr; only letters, digits and . _ + - / are allowed, and no shell is involved.
  - `argv:` Fixed command line arguments placed before the call's own arguments, one list entry per argument.
  - `args:` The types of the arguments the body passes, such as [:string]; they become extra arguments or stdin.
  - `returns:` The result type; always :string, the program's standard output.
  - `pass:` How arguments reach the program: :argv adds them to the command line (the default), :stdin writes one string to standard input.
  - `async:` Not supported: a subprocess is blocking, so `async: true` on cmd_fn is refused.
- Takes no block

### `script_fn`

A function that runs inline code in an interpreter such as python3 or ruby and returns its output as a string.

- Allowed inside: `server`
- Positional arguments: `name` (snake_case symbol)
- Keyword arguments: `interpreter:` (string literal, required), `code:` (string literal, required), `args:` (array of type symbols, required), `returns:` (one of :string, required), `flag:` (string literal, optional), `async:` (true or false, optional)
  - `interpreter:` The interpreter to run, such as python3, ruby, node, sh or bash.
  - `code:` The source text that the interpreter runs; it receives the call's arguments as command line arguments.
  - `args:` The types of the arguments the body passes, such as [:string].
  - `returns:` The result type; always :string, the script's standard output.
  - `flag:` The interpreter option that takes the code (such as -c); needed only for an interpreter the compiler does not know.
  - `async:` Not supported: a subprocess is blocking, so `async: true` on script_fn is refused.
- Takes no block

## Examples

A string tool:

```ruby
server "labeler", version: "0.1.0" do
  params :TextParams do
    field :text, :string, description: "The text to classify"
  end

  tool :label, params: :TextParams, description: "Say what kind of URL a string looks like" do
    body do |text|
      if text.start_with?("https://")
        "secure"
      elsif text.match?(/\Ahttp:/)
        "plain"
      else
        "other"
      end
    end
  end

  transport :stdio
end
```

A tool backed by a subprocess, with no Rust:

```ruby
server "shouter", version: "0.1.0" do
  cmd_fn :run_upper, program: "tr", argv: ["a-z", "A-Z"], args: [:string], returns: :string, pass: :stdin

  params :TextParams do
    field :text, :string
  end

  tool :upper, params: :TextParams, description: "Uppercase text with tr" do
    body do |text|
      rust(:run_upper, text)
    end
  end

  transport :stdio
end
```
