# Third-party Notices

Tested dependency snapshot for optional Zeep mode, Windows / Python 3.12.14.

This project uses Zeep directly; python-onvif-zeep is a design reference, not a bundled dependency. Project code is MIT; dependencies retain their own licenses. Library binaries and sources are installed separately by pip.

| Package | Version | License metadata | Notices | Source distribution |
| --- | --- | --- | --- | --- |
| attrs | 26.1.0 | MIT | [LICENSE](third_party/licenses/attrs-26.1.0/LICENSE) | [Source files](https://pypi.org/project/attrs/26.1.0/#files) |
| certifi | 2026.10.23 | MPL-2.0 | [LICENSE](third_party/licenses/certifi-2026.10.23/LICENSE) | [Source files](https://pypi.org/project/certifi/2026.10.23/#files) |
| charset-normalizer | 3.5.2 | MIT | [LICENSE](third_party/licenses/charset-normalizer-3.5.2/LICENSE) | [Source files](https://pypi.org/project/charset-normalizer/3.5.2/#files) |
| idna | 3.20 | BSD-3-Clause | [LICENSE.md](third_party/licenses/idna-3.20/LICENSE.md) | [Source files](https://pypi.org/project/idna/3.20/#files) |
| isodate | 0.7.2 | BSD-3-Clause | [LICENSE](third_party/licenses/isodate-0.7.2/LICENSE) | [Source files](https://pypi.org/project/isodate/0.7.2/#files) |
| lxml | 6.1.3 | BSD-3-Clause | [LICENSE.txt](third_party/licenses/lxml-6.1.3/LICENSE.txt), [LICENSES.txt](third_party/licenses/lxml-6.1.3/LICENSES.txt) | [Source files](https://pypi.org/project/lxml/6.1.3/#files) |
| platformdirs | 4.14.5 | MIT | [LICENSE](third_party/licenses/platformdirs-4.14.5/LICENSE) | [Source files](https://pypi.org/project/platformdirs/4.14.5/#files) |
| requests | 2.34.2 | Apache-2.0 | [LICENSE](third_party/licenses/requests-2.34.2/LICENSE), [NOTICE](third_party/licenses/requests-2.34.2/NOTICE) | [Source files](https://pypi.org/project/requests/2.34.2/#files) |
| requests-file | 3.0.1 | Apache 2.0 | [LICENSE](third_party/licenses/requests-file-3.0.1/LICENSE) | [Source files](https://pypi.org/project/requests-file/3.0.1/#files) |
| requests-toolbelt | 1.0.0 | Apache 2.0 | [LICENSE](third_party/licenses/requests-toolbelt-1.0.0/LICENSE) | [Source files](https://pypi.org/project/requests-toolbelt/1.0.0/#files) |
| urllib3 | 2.8.0 | MIT | [LICENSE.txt](third_party/licenses/urllib3-2.8.0/LICENSE.txt) | [Source files](https://pypi.org/project/urllib3/2.8.0/#files) |
| zeep | 4.3.3 | MIT | [LICENSE](third_party/licenses/zeep-4.3.3/LICENSE) | [Source files](https://pypi.org/project/zeep/4.3.3/#files) |

License metadata is an index; the complete notice files control. Zeep contains additional attribution; lxml includes native-library notices. Retain the notices applicable to the actual deployed artifacts. certifi is MPL-2.0: retain its notice and provide recipients source availability information when distributing covered software. Its version-specific source link is listed above. See [licensing details](docs/licensing.md).

The optional dependency version snapshot is [requirements-zeep.lock](requirements-zeep.lock). Re-audit when versions, target-platform wheels, or container contents change. Setuptools/pip are build tools; their distributions are not bundled here. Official schemas are fetched separately and are not MIT project code.
