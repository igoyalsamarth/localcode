# Minimal GitHub agent sandbox: git + GitHub CLI only (lint/format/test stay in CI).
#
# LangChain Deep Agents + langchain-daytona use deepagents.backends.sandbox.BaseSandbox for
# read_file / write / glob / ls: those all shell out to ``python3 -c ...``. Stock Daytona
# language snapshots include Python; this custom image must too or file tools fail (often
# reported as "file not found" because any execute failure maps to that message).

FROM ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
  ca-certificates curl git python3 \
  && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg -o /usr/share/keyrings/githubcli-archive-keyring.gpg \
  && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
  && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
  > /etc/apt/sources.list.d/github-cli.list \
  && apt-get update && apt-get install -y gh && rm -rf /var/lib/apt/lists/*

ENV PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
