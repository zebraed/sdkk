#!/bin/bash
# Mayaのmodulesフォルダへ展開して使えるZIPを作る
# 使い方: bash .github/scripts/build_zip.sh v2.1.1 [出力先のフォルダ]
set -eu

tag="$1"
cd "$(dirname "$0")/../.."
output="$(cd "${2:-.}" && pwd)"

stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT

git archive --prefix=sdkk/ "$tag" | tar -x -C "$stage"

# ZIPの直下に置く.modは、隣のsdkkフォルダを指す。フォルダ内の.modは同じ名前でぶつかるため、ZIPには入れない
sed 's/^\(+ sdkk [^ ]*\) \.\r\{0,1\}$/\1 sdkk/' "$stage/sdkk/sdkk.mod" > "$stage/sdkk.mod"
rm "$stage/sdkk/sdkk.mod"

if ! grep -q '^+ sdkk [^ ]* sdkk' "$stage/sdkk.mod"; then
  echo "::error::Could not point sdkk.mod at the sdkk folder"
  exit 1
fi

(cd "$stage" && zip -qr "$output/sdkk-$tag.zip" sdkk.mod sdkk)
echo "$output/sdkk-$tag.zip"
