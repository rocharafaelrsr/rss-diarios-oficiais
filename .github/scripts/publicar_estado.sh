#!/usr/bin/env bash
set -euo pipefail

SOURCE="${1:?Informe dodf ou dou}"
STATUS_FILE="docs/status-${SOURCE}.json"
PATHS=(data/items.json docs/feeds "$STATUS_FILE")

if [[ "$SOURCE" != "dodf" && "$SOURCE" != "dou" ]]; then
  echo "::error::Fonte inválida: $SOURCE"
  exit 2
fi

git config user.name "rss-diarios-bot"
git config user.email "rss-diarios-bot@users.noreply.github.com"

commit_current_state() {
  git add "${PATHS[@]}"
  if git diff --cached --quiet; then
    echo "Sem alterações para publicar."
    return 1
  fi
  git commit -m "chore(rss): atualizar ${SOURCE^^} [skip ci]"
  return 0
}

validate_feeds() {
  python - <<'PY'
from pathlib import Path
from xml.etree import ElementTree as ET

paths = sorted(Path("docs/feeds").glob("*.xml"))
if not paths:
    raise SystemExit("Nenhum feed foi gerado.")
for path in paths:
    root = ET.parse(path).getroot()
    assert root.tag == "rss", f"{path}: raiz inválida"
PY
}

run_collection() {
  if [[ "$SOURCE" == "dodf" ]]; then
    python src/main_dodf.py
  else
    # O fluxo do DOU permanece exatamente no entrypoint original.
    python src/main.py --source "$SOURCE"
  fi
}

retry_collection_status=0

if ! commit_current_state; then
  exit 0
fi

for attempt in 1 2 3; do
  if git push origin HEAD:main; then
    # A coleta inicial é verificada pelo workflow. Nas tentativas refeitas, o
    # status precisa ser propagado depois que o diagnóstico já foi publicado.
    exit "$retry_collection_status"
  fi

  if [[ "$attempt" -eq 3 ]]; then
    echo "::error::Não foi possível publicar após 3 tentativas."
    exit 1
  fi

  echo "A main avançou durante a coleta; refazendo ${SOURCE^^} sobre o estado mais recente (tentativa $((attempt + 1))/3)."
  git fetch origin main
  git reset --hard origin/main

  set +e
  run_collection
  retry_collection_status=$?
  set -e

  validate_feeds

  if ! commit_current_state; then
    exit "$retry_collection_status"
  fi
done
