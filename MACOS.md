# Running DXB RUNWAY on macOS

## Which download to use

- Apple M1, M2, M3, M4 or newer: `DXB-RUNWAY-macOS-Apple-Silicon.zip`
- Intel processor: `DXB-RUNWAY-macOS-Intel.zip`

Open **Apple menu → About This Mac** if you are unsure. The Chip line identifies Apple Silicon; older Macs show Processor: Intel.

## Install

1. Download the correct ZIP from the private GitHub release and unzip it.
2. Drag `DXB RUNWAY.app` into Applications.
3. On first launch, Control-click the app, choose **Open**, then confirm **Open**.

The release is ad-hoc signed but not Apple-notarised. A company-managed Mac may prohibit non-notarised applications. If the Open option is blocked by company policy, ask IT to approve the app or provide an Apple Developer signing identity for a notarised company build. Administrator access is not otherwise required when the app is placed in your user Applications folder.

## Move your Windows data

1. In DXB RUNWAY on Windows, open **Settings → Local data & privacy → Create portable backup**.
2. Save the `.dxbr` file somewhere available to the Mac.
3. Start DXB RUNWAY on the Mac and complete the short first-run setup.
4. Open **Settings → Local data & privacy → Restore backup** and choose the `.dxbr` file.

This transfers the SQLite database, settings and locally stored receipt files in one portable backup.

macOS stores the live database below the user Library through Qt's standard application-data location. Use **Settings → Open local data folder** instead of navigating there manually.
