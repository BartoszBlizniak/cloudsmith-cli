# Build environment for the glibc binaries: AlmaLinux 8 (glibc 2.28) with the
# packages the build needs already installed, so a build does not download them
# from the AlmaLinux mirrors every time.
FROM almalinux:8@sha256:4a87d2615a770506e204c27d6248ac97f4df67f4e41e2e9c47c81f0ed0be98cb

RUN dnf install -y gcc binutils file \
    && dnf clean all
