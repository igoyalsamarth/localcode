# Minimal GitHub agent sandbox: git + GitHub CLI only (lint/format/test stay in CI).
# OS user matches the app bot-style identity used in the container; git author for commits
# still comes from GIT_AUTHOR_* in the worker env (e.g. YourApp[bot] + users.noreply email).

FROM ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive
# Linux username (no brackets); align gragent-be DAYTONA_SANDBOX_USER / default home with this.
ARG SANDBOX_USER=greagents

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl git \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg -o /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y gh && rm -rf /var/lib/apt/lists/*

RUN useradd -m -s /bin/bash "${SANDBOX_USER}"

USER ${SANDBOX_USER}
WORKDIR /home/${SANDBOX_USER}

ENV PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
