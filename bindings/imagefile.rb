# typed: true
# A home for the image crate. Dependencies are declared per binding but land in
# the crate's Cargo.toml, so declaring it here lets a rust_file elsewhere write
# `use image::...` with no further wiring. The one function is small and true.
module ImageFile
  extend T::Sig
  extend RmcpDsl::BindingDsl

  crate "image", "0.25"

  # The size of a file in bytes; nil when it cannot be read.
  rust "std::fs::metadata(path).ok().map(|m| m.len() as i64)"
  no_reference "reads the host filesystem; the reference run has no file to point at"
  sig { params(path: String).returns(T.nilable(I64)) }
  def self.size(path) = raise(NotImplementedError, "no Ruby stand-in")
end
