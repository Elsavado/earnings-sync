#!/usr/bin/env bash
# Keeps the laptop copy in step with Drive: every completed folder of 20 models is copied as
# soon as it is full. Runs until stopped; the next folder to fetch is remembered in a file.
cd /c/Users/sekwa/Downloads/earnings-sync
DEST="/c/Users/sekwa/Excel Models"
WORK="${TMPDIR:-/tmp}/excel-models-fetch"  # not TMP: gh keeps its temporary zip in $TMP
NEXT="$DEST/.next_folder"
mkdir -p "$DEST"
[ -f "$NEXT" ] || echo 2 > "$NEXT"
while true; do
  k=$(cat "$NEXT")
  started=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  gh workflow run excel-package.yml -f folder="${k}+" -f complete=true >/dev/null 2>&1
  sleep 12
  # Only the run this loop just started (created at or after the dispatch time).
  id=$(gh run list --workflow excel-package.yml -L 5 --json databaseId,createdAt        -q "[.[] | select(.createdAt >= \"$started\")] | last | .databaseId")
  [ -n "$id" ] || { sleep 30; continue; }
  # Poll (gh run watch needs a terminal and returns at once in the background).
  until [ "$(gh run view "$id" --json status -q .status 2>/dev/null)" = completed ]; do sleep 15; done
  if [ "$(gh run view "$id" --json conclusion -q .conclusion)" = success ]; then
    rm -rf "$WORK"; gh run download "$id" -D "$WORK" >/dev/null || echo "$(date -u +%H:%M) download of run $id failed"
    copied=0
    for d in "$WORK"/*/Folder*; do
      [ -d "$d" ] || continue
      n=$(ls "$d" | wc -l)
      [ "$n" -eq 20 ] || continue
      cp -r "$d" "$DEST/" && copied=$((copied+1))
    done
    if [ "$copied" -gt 0 ]; then
      echo $((k + copied)) > "$NEXT"
      echo "$(date -u +%H:%M) copied folders $k-$((k + copied - 1))"
      continue
    fi
  fi
  sleep 240
done
