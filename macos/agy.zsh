# Source from ~/.zshrc. The binary remains available through `command agy`.
agy() {
  local unlocker="$HOME/dev/ai/avt-antigravity-unlocker/macos/ag_unlocker_mac.sh"
  local cli="$HOME/.local/bin/agy" app rc
  local -a targets=(--cli-path "$cli")
  for app in /Applications/Antigravity.app "$HOME/Applications/Antigravity.app" \
    '/Applications/Antigravity IDE.app' "$HOME/Applications/Antigravity IDE.app"; do
    [[ -d "$app" ]] && targets+=(--app "$app")
  done
  if bash "$unlocker" --check "${targets[@]}"; then
    rc=0
  else
    rc=$?
  fi
  case "$rc" in
    0) ;;
    10) bash "$unlocker" --ensure-patched "${targets[@]}" || return $? ;;
    *) return "$rc" ;;
  esac
  # Use the exact binary checked above, even if PATH changes later.
  command "$cli" "$@"
}
