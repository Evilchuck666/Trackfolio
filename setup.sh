#!/usr/bin/env bash
# Start from a checkout or ZIP without requiring Python or uv on PATH.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$ROOT"

fail() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    cat <<'HELP'
Trackfolio: preparación completa desde las fuentes.
Uso: bash setup.sh [--core | --gui] [--platform offscreen|xcb|wayland]
                  [--skip-editor] [--non-interactive] [--yes] [--open-code]
                  [--qt-timeout SEGUNDOS]
Por defecto prepara la GUI, las herramientas de desarrollo y VS Code.
Las instalaciones del sistema y de un editor nuevo requieren confirmación.
--yes autoriza esas instalaciones; --non-interactive no realiza preguntas.
Para ejecutar uv sin repetir la preparación: bash setup.sh --run-uv COMANDO ...
HELP
    exit 0
fi

for file in pyproject.toml .python-version uv.lock scripts/setup.py; do
    [[ -s "$file" ]] || fail "Falta $file. Descarga el repositorio completo."
done

# Only the initial uv installer needs this small, dependency-free TOML reader.
# uv itself validates the complete project configuration before it is selected.
REQUIREMENT="$(awk '
    /^[[:space:]]*\[tool\.uv\][[:space:]]*$/ { section = 1; next }
    /^[[:space:]]*\[/ { section = 0 }
    section && /^[[:space:]]*required-version[[:space:]]*=/ {
        sub(/^[^=]*=[[:space:]]*/, "")
        sub(/[[:space:]]*#.*/, "")
        gsub(/["\047[:space:]]/, "")
        print; exit
    }
' pyproject.toml)"
range_pattern='^>=([0-9]+\.[0-9]+\.[0-9]+),<([0-9]+\.[0-9]+(\.[0-9]+)?)$'
[[ "$REQUIREMENT" =~ $range_pattern ]] || fail "Rango de uv inválido en pyproject.toml."
MINIMUM="${BASH_REMATCH[1]}"
MAXIMUM="${BASH_REMATCH[2]}"
awk -v minimum="$MINIMUM" -v maximum="$MAXIMUM" 'BEGIN {
    split(minimum, low, "."); split(maximum, high, ".")
    for (i = 1; i <= 3; i++) {
        if (low[i] + 0 < high[i] + 0) exit 0
        if (low[i] + 0 > high[i] + 0) exit 1
    }
    exit 1
}' || fail "El mínimo de uv debe ser inferior al máximo exclusivo."
PYTHON_VERSION="$(< .python-version)"
PYTHON_VERSION="${PYTHON_VERSION//$'\r'/}"
[[ "$PYTHON_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail ".python-version inválido."

LOCAL_UV="$ROOT/.tools/uv"
UV=""
compatible() {
    [[ -x "$1" ]] && "$1" version --short --offline --project "$ROOT" >/dev/null 2>&1
}
while IFS= read -r candidate; do
    if compatible "$candidate"; then
        UV="$candidate"
        break
    fi
done < <(type -a -P uv 2>/dev/null || true)
if [[ -z "$UV" ]] && compatible "$LOCAL_UV/uv"; then
    UV="$LOCAL_UV/uv"
fi

if [[ "${1:-}" == "--run-uv" ]]; then
    shift
    [[ -n "$UV" ]] || fail "No hay uv compatible. Ejecuta primero bash setup.sh."
    [[ $# -gt 0 ]] || fail "Indica el comando de uv después de --run-uv."
    exec "$UV" "$@"
fi

ensure_downloader() {
    if command -v curl >/dev/null 2>&1 || command -v wget >/dev/null 2>&1; then
        return
    fi
    local consent=0 non_interactive=0 answer prefix=()
    for argument in "$@"; do
        [[ "$argument" != "--yes" ]] || consent=1
        [[ "$argument" != "--non-interactive" ]] || non_interactive=1
    done
    local manager=""
    for name in apt-get pacman dnf; do
        if command -v "$name" >/dev/null 2>&1; then manager="$name"; break; fi
    done
    [[ -n "$manager" ]] || fail "Instala curl o wget y vuelve a ejecutar el script."
    if [[ $consent == 0 && $non_interactive == 0 && -t 0 ]]; then
        printf 'Falta curl o wget. ¿Instalar curl con %s? [s/N] ' "$manager"
        read -r answer
        [[ "$answer" != "s" && "$answer" != "S" && "$answer" != "y" && "$answer" != "Y" ]] || consent=1
    fi
    [[ $consent == 1 ]] || fail "Se necesita curl o wget para descargar uv; instalación no autorizada."
    if [[ $EUID != 0 ]]; then
        command -v sudo >/dev/null 2>&1 || fail "Necesitas sudo o instalar curl manualmente."
        prefix=(sudo)
    fi
    case "$manager" in
        apt-get)
            "${prefix[@]}" apt-get update
            "${prefix[@]}" apt-get install --no-install-recommends -y curl ;;
        pacman) "${prefix[@]}" pacman -S --needed --noconfirm curl ;;
        dnf) "${prefix[@]}" dnf install -y curl ;;
    esac
}

if [[ -z "$UV" ]]; then
    ensure_downloader "$@"
    mkdir -p "$LOCAL_UV"
    installer="$(mktemp "$LOCAL_UV/.installer.XXXXXX")"
    trap 'rm -f -- "$installer"' EXIT
    url="https://astral.sh/uv/$MINIMUM/install.sh"
    printf 'Descargando uv %s para este proyecto, sin modificar el sistema ni el shell.\n' "$MINIMUM"
    if command -v curl >/dev/null 2>&1; then
        curl --fail --location --silent --show-error --connect-timeout 15 --max-time 120 --retry 2 \
            "$url" --output "$installer"
    else
        wget --quiet --timeout=30 --tries=3 "$url" --output-document="$installer"
    fi
    UV_UNMANAGED_INSTALL="$LOCAL_UV" UV_NO_MODIFY_PATH=1 sh "$installer"
    compatible "$LOCAL_UV/uv" || fail "La instalación de uv no cumple $REQUIREMENT."
    UV="$LOCAL_UV/uv"
    rm -f -- "$installer"
    trap - EXIT
fi

printf 'Usando uv: %s\n' "$UV"
"$UV" run --no-project --managed-python --python "$PYTHON_VERSION" python -m scripts.setup --uv "$UV" "$@"
