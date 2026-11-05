# Dependencies and Licensing

[README](../README.md) | [Documentation index](index.md)

## Project code and reference repository

Original project code is provided under [MIT](../LICENSE). The 0.2.0 adapter was
written for this project after studying
[FalkTannhaeuser/python-onvif-zeep](https://github.com/FalkTannhaeuser/python-onvif-zeep/tree/zeep).
No source from that repository was copied or vendored. Its
[MIT notice](https://github.com/FalkTannhaeuser/python-onvif-zeep/blob/zeep/LICENSE)
identifies Quatanium Co., Ltd.; retain that notice if future changes copy substantial
portions. The `onvif-zeep` distribution is not required by this package.

## Optional dependency stack

`pyproject.toml` declares `zeep>=4.3,<5` under the `zeep` extra. The base installation
has no third-party runtime dependencies. Setuptools is a build dependency.

The exact tested dependency inventory and license copies are provided in
[THIRD_PARTY_NOTICES](../THIRD_PARTY_NOTICES.md),
[dependencies.json](../third_party/dependencies.json), and
`third_party/licenses/`. Runtime libraries themselves are installed by pip, not
embedded in this ZIP. `requirements-zeep.lock` pins the tested dependency versions.

The inventory includes MIT, BSD, Apache-2.0, and MPL-2.0 licenses; it must not be
described as an all-MIT dependency stack. No noncommercial-only restriction was
found in the recorded dependency notices. These licenses permit commercial use
subject to their respective conditions.

- Retain required copyright/license notices for MIT/BSD components.
- Retain Apache-2.0 license and applicable NOTICE material, and mark changes when required.
- Zeep's license file includes additional attribution for incorporated work.
- lxml wheels may contain native libraries with additional notices; retain its
  LICENSES file and audit the actual target-platform wheel/container contents.
- `certifi` is MPL-2.0. When distributing covered software, preserve MPL notices
  and provide recipients the required source availability information. Changes to
  covered files have file-level source obligations; this is not a blanket requirement
  to publish unrelated application code. See the [Mozilla MPL FAQ](https://www.mozilla.org/en-US/MPL/2.0/FAQ/).

Version-specific PyPI source-download links accompany the inventory, including
certifi. If the final product distributes patched dependencies, also make the
corresponding modified covered source available as required. This source ZIP's
inventory does not cover uninspected Jetson OS packages, codecs, or future dependencies.

## Official WSDL and XSD resources

The downloader retrieves official ONVIF/W3C/OASIS resources only when explicitly run.
They are separately copyrighted standards resources, not project MIT code.
Preserve notices in those files and assess their terms when distributing a prepared
bundle or container. The repository ignores `wsdl_bundle/` to avoid accidentally
relabeling or committing downloaded material. Runtime requires the prepared bundle
only when the Zeep adapter is selected.

Dependency notices and version inventory must be regenerated after changing the
dependency resolution. A successful pip installation does not perform that review.
