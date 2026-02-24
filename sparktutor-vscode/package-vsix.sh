#!/usr/bin/env bash
# Package the SparkTutor VS Code extension as a .vsix file.
# Builds a standard VSIX (which is just a ZIP with specific structure).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VERSION=$(node -e "console.log(require('./package.json').version)")
VSIX_NAME="sparktutor-${VERSION}.vsix"

echo "==> Building TypeScript..."
cd "$SCRIPT_DIR"
npm run build

echo "==> Preparing VSIX staging area..."
STAGING=$(mktemp -d)
EXTENSION_DIR="$STAGING/extension"
mkdir -p "$EXTENSION_DIR"

# Copy extension files
cp package.json "$EXTENSION_DIR/"
cp -r out "$EXTENSION_DIR/"
cp -r media "$EXTENSION_DIR/"

# Bundle Python source
mkdir -p "$EXTENSION_DIR/python_src"
cp -r "$PROJECT_ROOT/src/sparktutor" "$EXTENSION_DIR/python_src/sparktutor"

# Clean Python artifacts
find "$EXTENSION_DIR/python_src" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find "$EXTENSION_DIR/python_src" -name "*.pyc" -delete 2>/dev/null || true

# Create [Content_Types].xml (required by VSIX format)
cat > "$STAGING/[Content_Types].xml" << 'XMLEOF'
<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension=".json" ContentType="application/json"/>
  <Default Extension=".js" ContentType="application/javascript"/>
  <Default Extension=".css" ContentType="text/css"/>
  <Default Extension=".svg" ContentType="image/svg+xml"/>
  <Default Extension=".py" ContentType="text/x-python"/>
  <Default Extension=".yaml" ContentType="text/yaml"/>
  <Default Extension=".txt" ContentType="text/plain"/>
  <Default Extension=".vsixmanifest" ContentType="text/xml"/>
</Types>
XMLEOF

# Create extension.vsixmanifest
PUBLISHER=$(node -e "console.log(require('./package.json').publisher)")
NAME=$(node -e "console.log(require('./package.json').name)")
DISPLAY_NAME=$(node -e "console.log(require('./package.json').displayName)")
DESCRIPTION=$(node -e "console.log(require('./package.json').description)")
ENGINE=$(node -e "console.log(require('./package.json').engines.vscode)")

cat > "$STAGING/extension.vsixmanifest" << MANIFESTEOF
<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011" xmlns:d="http://schemas.microsoft.com/developer/vsx-schema-design/2011">
  <Metadata>
    <Identity Language="en-US" Id="${NAME}" Version="${VERSION}" Publisher="${PUBLISHER}"/>
    <DisplayName>${DISPLAY_NAME}</DisplayName>
    <Description xml:space="preserve">${DESCRIPTION}</Description>
    <Categories>Education</Categories>
    <Properties>
      <Property Id="Microsoft.VisualStudio.Code.Engine" Value="${ENGINE}"/>
      <Property Id="Microsoft.VisualStudio.Code.ExtensionDependencies" Value=""/>
      <Property Id="Microsoft.VisualStudio.Code.ExtensionPack" Value=""/>
      <Property Id="Microsoft.VisualStudio.Code.ExtensionKind" Value="workspace"/>
      <Property Id="Microsoft.VisualStudio.Code.LocalizedLanguages" Value=""/>
      <Property Id="Microsoft.VisualStudio.Services.GitHubFlavoredMarkdown" Value="true"/>
    </Properties>
  </Metadata>
  <Installation>
    <InstallationTarget Id="Microsoft.VisualStudio.Code"/>
  </Installation>
  <Dependencies/>
  <Assets>
    <Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true"/>
  </Assets>
</PackageManifest>
MANIFESTEOF

echo "==> Creating VSIX archive..."
cd "$STAGING"
zip -r "$SCRIPT_DIR/$VSIX_NAME" . -x "*.DS_Store" > /dev/null

echo "==> Cleaning up..."
rm -rf "$STAGING"

echo ""
echo "Done! VSIX file:"
ls -lh "$SCRIPT_DIR/$VSIX_NAME"
echo ""
echo "Install with:"
echo "  code --install-extension $SCRIPT_DIR/$VSIX_NAME"
