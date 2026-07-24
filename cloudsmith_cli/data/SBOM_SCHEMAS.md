Bundled SBOM schemas
====================

The Cloudsmith CLI validates SBOMs offline with version-pinned copies of the
official JSON schemas listed below. File endings are normalized to match this
repository's policy; schema content is otherwise unchanged. The schema files
are redistributed under their respective project licenses.

- CycloneDX 1.6.1 (`cyclonedx-bom-1.6.schema.json`,
  `cyclonedx-jsf-0.82.schema.json`, and
  `cyclonedx-spdx-3.24.0.schema.json`) from tag `1.6.1`, commit
  `8a27bfd1be5be0dcb2c208a34d2f4fa0b6d75bd7`. These schemas are licensed
  under Apache-2.0 by the OWASP Foundation.
- SPDX 2.3 (`spdx-2.3.schema.json`) from tag `v2.3`, commit
  `f7f7bce5511a23fe3c9d8a1edca0d870a7d0bea5`. The SPDX specification is
  licensed under the Creative Commons Attribution 3.0 Unported license.

Upstream sources:

- https://github.com/CycloneDX/specification/tree/1.6.1/schema
- https://github.com/spdx/spdx-spec/blob/v2.3/schemas/spdx-schema.json
- https://creativecommons.org/licenses/by/3.0/
