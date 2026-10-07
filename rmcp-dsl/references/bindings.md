# Bindings

A binding is a typed function backed by a Rust crate (or compiled from Ruby). The compiler ships none:
they are yours, kept in a `bindings/` folder in the SAME directory as the DSL file that uses them (nothing
is searched beyond that). `use_bindings :words` at the top of the server loads `bindings/words.rb` from
there (parsed, never run), and a body calls it as `Module.method(args)`. A missing file is an error that
names the path it looked for. A binding file looks like this:

```ruby
# bindings/words.rb, in the same directory as the DSL file
module Words
  extend T::Sig
  extend RmcpDsl::BindingDsl

  sig { params(s: String).returns(String) }
  def self.shout(s) = s.upcase + "!"
  example :shout, "hello", expect: "HELLO!"
end
```

- `sig` gives the types: `String`, `Float`, `I32`, `I64`, `T::Boolean`, `T::Array[String]`,
  `T::Array[I64]`, and `T.nilable(...)` of those as a return type.
- Without a `rust` line the Ruby body is compiled to Rust and is the implementation. With
  `rust "heck::ToSnakeCase::to_snake_case(s)"` above the method, that Rust expression does the work and the
  Ruby body is only the reference the tests compare it against. `no_reference "why"` marks a function with
  no Ruby stand-in (an HTML parser, DNS).
- `crate "heck", "0.5"` adds a Cargo dependency. `example :method, args..., expect: value` documents a
  function; the test generators in the compiler's repository run examples, the compiler itself only reads
  the types.
- `bindings/heck.rb`, `html.rb`, `url.rb`, `net.rb` and `words.rb` in the repository's `examples/` folder are
  working references to copy from.

A nil-able return type means "does not exist" or "does not parse", and a binding never fails by
itself: the body decides what that means. Use `|| default` to carry on, `|| raise("message")` to
fail the call, `|| []` for a nil-able list, or `.nil?` to test. For example:

```ruby
found = Html.select(page, css) || raise("invalid CSS selector: #{css}")
host = Url.host(url) || "(none)"
```
