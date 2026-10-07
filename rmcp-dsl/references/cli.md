# Command line

```
rmcp_dsl check FILE.rb [--format json]
rmcp_dsl build FILE.rb [-o DIR] [--release] [--emit-only]
rmcp_dsl run   FILE.rb [-o DIR] [--release]
rmcp_dsl init  NAME [-o DIR] [--force] [--no-bindings]
rmcp_dsl check FILE.rb --format json --types
rmcp_dsl rbi   FILE.rb... [-o DIR]
rmcp_dsl lsp
rmcp_dsl skill [-o DIR]
rmcp_dsl FILE.rb -o DIR | --dump-ir | --check      (the original form)
```

- `check` validates only and writes nothing. With `--format json` it prints one document:
  `{"ok":true,"file":...,"notes":[{code,level,line,col,message,file}],"hidden":N}`, or on failure
  `{"ok":false,"file":...,"error":{file,line,col,message,suggestions}}`. Exit status 1 on failure. An
  error names the valid choices and, for a likely typo, suggests the nearest name (`suggestions`). With
  `--types` the success document also has `"types"`: `[{line,col,end_line,end_col,kind,type,name?}]`, the
  type the compiler inferred for every parameter, local and expression (1-based lines and columns,
  `end_col` exclusive).
- `rbi` writes Sorbet signatures for the helpers the files declare to `sorbet/rbi/rmcp_dsl/dsl_helpers.rbi`.
- `lsp` runs a language server on stdio: diagnostics with quick fixes, hover types, inlay hints and
  completion. Name DSL files `*.rmcp.rb` so an editor can attach it.
- `build` writes the crate to `-o DIR` (default `build/NAME`) and runs `cargo build`; `--emit-only`
  stops after writing and `--release` is passed to cargo. The crate is a standalone cargo workspace.
  Rust errors in generated code are printed as `FILE:LINE: error: ... (in tool `name`)`.
- `run` builds, then starts the server on stdio. Nothing else may write to stdout while it runs.
- `init` writes `NAME.rmcp.rb` (a minimal server) and a `bindings/` folder (with a
  `.gitkeep`) into `-o DIR` (default `.`). It refuses to overwrite an existing file
  without `--force`, and `--no-bindings` skips the folder.
- `skill` writes this skill into `-o DIR` (default the current directory) as `rmcp-dsl/`.
- `--warn SPEC` and `--notice SPEC` choose which notifications are printed (`all`, `none`, codes).
- `--dump-ir` prints the intermediate representation as JSON.

`build` and `run` need `cargo` on the PATH; `check` needs only Ruby.
