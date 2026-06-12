FROM alpine:3.21

LABEL maintainer="support@cloudsmith.io"
LABEL description="Official Cloudsmith CLI, now served in a handy container"

ENV PATH="/opt/cloudsmith:${PATH}"

ARG TARGETARCH
ARG CLOUDSMITH_CLI_VERSION
ARG CLOUDSMITH_NAMESPACE
ARG CLOUDSMITH_REPO

# Ship the standalone musl binary for the image's architecture — no Python
# runtime in the image. The archive extracts to /opt/cloudsmith/.
RUN apk add --no-cache curl bash ca-certificates \
 && case "${TARGETARCH}" in \
      amd64) CS_ARCH="x86_64" ;; \
      arm64) CS_ARCH="aarch64" ;; \
      *) echo "Unsupported architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
 && curl -1sLf "https://dl.cloudsmith.io/public/${CLOUDSMITH_NAMESPACE}/${CLOUDSMITH_REPO}/raw/names/cloudsmith-cli-linux-${CS_ARCH}-musl/versions/${CLOUDSMITH_CLI_VERSION}/cloudsmith-${CLOUDSMITH_CLI_VERSION}-linux-${CS_ARCH}-musl.tar.gz" \
    | tar -xz -C /opt

# Run as a non-root user
RUN adduser -D -u 1000 cloudsmith
USER cloudsmith

# Default command
ENTRYPOINT [ "cloudsmith" ]
