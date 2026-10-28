#!/bin/bash
# how to use: bash .github/scripts/check_version.sh v2.1.1
set -eu

tag="$1"
cd "$(dirname "$0")/../.."

tag_version="${tag#v}"
init_version=$(tr -d '\r' < __init__.py | sed -n 's/^__version__ = "\(.*\)"$/\1/p')
mod_version=$(tr -d '\r' < sdkk.mod | sed -n 's/^+ sdkk \([^ ]*\) .*$/\1/p')
echo "tag=$tag_version __init__.py=$init_version sdkk.mod=$mod_version"

if [ "$tag_version" != "$init_version" ] || [ "$tag_version" != "$mod_version" ]; then
  echo "::error::The versions of the tag, __init__.py, and sdkk.mod must match"
  exit 1
fi
