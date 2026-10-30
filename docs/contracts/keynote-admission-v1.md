# Conditional Keynote admission v1

`.key` is ambiguous: a presentation and private cryptographic material may use
the same suffix. A filename check therefore permits only staging; it does not
authorize CAS publication or an application launch.

`file_formats.keynote.inspect_keynote(path, expected_sha256=None,
expected_size=None)` returns a byte-bound `keynote_iwa_zip_v1` identity proof.
The reader accepts single-file ZIP containers with modern Keynote IWA structure,
including an optional single enclosing directory or bounded inner `Index.zip`.
It checks the document UUID and metadata, framed Snappy/protobuf records, the
Keynote root's show/super fields and an additional slide component. A matching
list of ZIP entry names alone is insufficient. Older XML-only generations,
encrypted documents and directory packages are not claimed as supported.

Apple documents that a presentation may be saved either as a single file or a
directory package. Directory packages are reported separately as
`keynote_directory_package_unsupported`; they are never silently imported as
unrelated component files. The operator can use Keynote's conversion to a
single file. [Apple Keynote package/single-file guidance](https://support.apple.com/en-ke/guide/keynote/tanaa443947b/mac).

The format identity reader follows primary reverse-engineering descriptions of
IWA framing and application-specific root messages; Apple does not publish a
complete IWA schema here. [SheetJS format notes](https://github.com/SheetJS/notes/blob/main/iwa/README.md),
[obriensp's original IWA research](https://github.com/obriensp/iWorkFileFormat/blob/master/Docs/index.md).
No third-party parser or executable is invoked.

Limits are explicit: 256 MiB container, 2,000 entries, 1 MiB central directory,
512 MiB declared total expansion, 16 MiB inner Index ZIP, 4 MiB per inspected IWA,
16 MiB decoded IWA and a one-second identity parsing budget. Before Python's ZIP
reader allocates its entry objects, a bounded central-directory pass checks the
actual entry count. Paths, local-vs-central names, links, special files,
encryption, unsupported compression, duplicate normalized names and obvious
secret-member filenames are rejected. No member is extracted to the filesystem.

Importer publication takes a private bounded snapshot and verifies its expected
SHA-256/size, then validates that exact snapshot before CAS publication. This
prevents a mutable source changing from a valid presentation into private key
material between format inspection and copying. Existing blobs and originals
are not overwritten. Receiver commit uses the same path after its own chunk
checksum verification; an invalid `.key` remains uncommitted and cannot publish
a blob, record, graph node or searchable content. Obvious secret filenames such
as `credentials.key`, `secret.key`, `id_rsa.key` and `.pem` retain their guards.

The record carries `content_validation` with identity, schema version, digest,
size and file format version. Filename-only capabilities explicitly state
`content_validation_required` and the import/open condition. Keynote content is
not indexed or internally rendered: filename/path metadata remain searchable.
Preview is metadata-only and enables opening only when the stored proof matches
the record's current digest and size. Renaming arbitrary bytes to `.key` cannot
make them externally openable.

`require_validated_keynote(record, path)` is the shared pre-launch guard. It is a
no-op for other suffixes. For `.key` it requires the matching record proof and
rechecks the exact verified named copy through one no-follow descriptor before
the existing explicit Mac application action. It does not launch anything.

Development checks include synthetic malformed/private-key/ZIP/IWA cases,
receiver restart, pre-CAS rejection, source replacement, conditional preview,
directory packages and independent public real-world format fixtures. The latter
were read from Apache Tika and kept only in private development evidence, with
source URLs and SHA-256 values:

- [Keynote 2013 fixture](https://github.com/apache/tika/blob/main/tika-parsers/tika-parsers-standard/tika-parsers-standard-modules/tika-parser-apple-module/src/test/resources/test-documents/testKeynote2013.key)
  — 274,397 bytes; SHA-256 `8da93f6b566bc9eb22f4791bbfd5f2179162f39bf80968187b164c33d31824db`.
- [Keynote 2018 fixture](https://github.com/apache/tika/blob/main/tika-parsers/tika-parsers-standard/tika-parsers-standard-modules/tika-parser-apple-module/src/test/resources/test-documents/testKeynote2018.key)
  — 54,228 bytes; SHA-256 `05edd6dfddd7cbbb2c74f8648a68de2e18dd97b36da5822f4b68795010bb935f`.

These checks establish admission and metadata behavior, not a human viewing the
presentation or the availability of Keynote on a particular Mac. Actual Mac
opening, bridge access and the final packaged runtime remain release checks.
