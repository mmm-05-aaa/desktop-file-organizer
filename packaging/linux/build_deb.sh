#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:-0.1.0~alpha}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD="$ROOT/build/linux"
DIST="$ROOT/dist"
ARCH="$(dpkg --print-architecture)"
ASSET_VERSION="${VERSION//\~/.}"
ASSET_NAME="desktop-organizer_${ASSET_VERSION}_${ARCH}.deb"

rm -rf "$BUILD"
mkdir -p "$BUILD/pyinstaller" "$BUILD/app" "$BUILD/pkg/DEBIAN" \
  "$BUILD/pkg/opt/desktop-organizer" "$BUILD/pkg/usr/bin" \
  "$BUILD/pkg/usr/share/applications" "$BUILD/pkg/usr/share/doc/desktop-organizer" "$DIST"

python3 -m PyInstaller --noconfirm --clean --onefile --windowed \
  --name desktop-file-organizer \
  --distpath "$BUILD/app" --workpath "$BUILD/pyinstaller" \
  --specpath "$BUILD" "$ROOT/organizer.py"
install -m 0755 "$BUILD/app/desktop-file-organizer" \
  "$BUILD/pkg/opt/desktop-organizer/desktop-file-organizer"
install -m 0644 "$ROOT/README.md" "$ROOT/LICENSE" \
  "$BUILD/pkg/usr/share/doc/desktop-organizer/"

cat > "$BUILD/pkg/DEBIAN/control" <<EOF
Package: desktop-organizer
Version: $VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Maintainer: mmm-05-aaa
Depends: libc6, libx11-6, libxext6, libxrender1, libxft2, libfontconfig1
Description: Previewable and reversible desktop file organizer
 A local Tk desktop utility that previews safe file moves and supports undo.
EOF
cat > "$BUILD/pkg/usr/bin/desktop-organizer" <<'EOF'
#!/bin/sh
exec /opt/desktop-organizer/desktop-file-organizer "$@"
EOF
chmod 0755 "$BUILD/pkg/usr/bin/desktop-organizer"
cat > "$BUILD/pkg/usr/share/applications/desktop-organizer.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Desktop Organizer
Name[zh_CN]=桌面整理器
Comment=Preview and safely organize desktop files
Exec=desktop-organizer
Icon=system-file-manager
Terminal=false
Categories=Utility;FileTools;
EOF
chmod 0644 "$BUILD/pkg/usr/share/applications/desktop-organizer.desktop"

dpkg-deb --build --root-owner-group "$BUILD/pkg" "$DIST/$ASSET_NAME"
dpkg-deb --info "$DIST/$ASSET_NAME"
