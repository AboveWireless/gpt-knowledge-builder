#!/usr/bin/env bash

set -euo pipefail

SKIP_TESTS=0
SKIP_DMG=0
CLEAN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-tests)
      SKIP_TESTS=1
      ;;
    --skip-dmg)
      SKIP_DMG=1
      ;;
    --clean)
      CLEAN=1
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
  shift
done

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
SPEC_PATH="$REPO_ROOT/packaging/macos/GPTKnowledgeBuilder.spec"
DIST_DIR="$REPO_ROOT/dist"
BUILD_DIR="$REPO_ROOT/build"
INSTALLER_DIR="$DIST_DIR/installer"

if [[ $CLEAN -eq 1 ]]; then
  rm -rf "$DIST_DIR" "$BUILD_DIR"
fi

cd "$REPO_ROOT"

echo "Installing build dependencies..."
python -m pip install -e ".[macos-build,extractors,ocr,ai]"

if [[ $SKIP_TESTS -eq 0 ]]; then
  echo "Running tests..."
  python -m pytest
fi

echo "Building macOS app with PyInstaller..."
python -m PyInstaller --noconfirm --clean "$SPEC_PATH"

VERSION="$(python -c "from knowledge_builder.version import APP_VERSION; print(APP_VERSION)")"
APP_PATH="$DIST_DIR/GPT Knowledge Builder.app"
ZIP_PATH="$DIST_DIR/GPTKnowledgeBuilder-$VERSION-macos.zip"

echo "Creating zip archive..."
rm -f "$ZIP_PATH"
ditto -c -k --sequesterRsrc --keepParent "$APP_PATH" "$ZIP_PATH"

if [[ $SKIP_DMG -eq 0 ]]; then
  mkdir -p "$INSTALLER_DIR"
  DMG_PATH="$INSTALLER_DIR/GPTKnowledgeBuilder-$VERSION-macos.dmg"
  echo "Creating DMG..."
  rm -f "$DMG_PATH"
  hdiutil create -volname "GPT Knowledge Builder" -srcfolder "$APP_PATH" -ov -format UDZO "$DMG_PATH"
else
  echo "Skipping DMG creation."
fi

echo "Build complete."
echo "App bundle: $APP_PATH"
echo "Zip archive: $ZIP_PATH"
if [[ $SKIP_DMG -eq 0 ]]; then
  echo "DMG: $INSTALLER_DIR/GPTKnowledgeBuilder-$VERSION-macos.dmg"
fi
