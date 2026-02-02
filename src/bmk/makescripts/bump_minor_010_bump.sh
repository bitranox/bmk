#!/usr/bin/env bash
# shellcheck shell=bash source=_bump_lib.sh
# Stage 01: Bump minor version
source "$(dirname "${BASH_SOURCE[0]}")/_bump_lib.sh" && _bump_init && _bump_run minor
