# Homebrew Cask for LocalRecall (macOS Apple Silicon)
#
# After publishing a GitHub Release, replace `sha256` with the checksum for
# `LocalRecall-v1.0.0-macOS-arm64.dmg` from the release's `SHA256SUMS.txt`.
#
# Install locally from this file:
#   brew install --cask ./packaging/homebrew/localrecall.rb
#
# Or publish in a personal tap repository (e.g. `Andacbasaran/homebrew-tap`
# under `Casks/localrecall.rb`) so users can install with:
#   brew tap Andacbasaran/tap
#   brew install --cask localrecall

cask "localrecall" do
  arch arm: "arm64"

  version "1.0.0"
  sha256 "REPLACE_WITH_SHA256_FROM_RELEASE_SHA256SUMS_TXT"

  url "https://github.com/Andacbasaran/LocalRecall/releases/download/v#{version}/LocalRecall-v#{version}-macOS-#{arch}.dmg",
      verified: "github.com/Andacbasaran/LocalRecall/"
  name "LocalRecall"
  desc "100% offline, privacy-first, 0 MB VRAM smart screen memory with instant OCR search and PII redaction"
  homepage "https://localrecall.andacbasaran.com/"

  livecheck do
    url :url
    strategy :github_latest
  end

  depends_on arch: :arm64
  depends_on macos: ">= :monterey"

  app "LocalRecall.app"

  caveats <<~EOS
    LocalRecall is MIT open-source software signed with an ad-hoc signature.
    If macOS Gatekeeper blocks first launch, run:
      xattr -cr "/Applications/LocalRecall.app"

    Grant Screen Recording permission in:
      System Settings -> Privacy & Security -> Screen & System Audio Recording
  EOS

  zap trash: [
    "~/Library/Application Support/LocalRecall",
    "~/Library/Caches/LocalRecall",
    "~/Library/LaunchAgents/com.andacbasaran.localrecall.plist",
    "~/Library/Preferences/com.andacbasaran.localrecall.plist",
    "~/Library/Saved Application State/com.andacbasaran.localrecall.savedState",
  ]
end
