// swift-tools-version:6.0
import PackageDescription

let package = Package(
    name: "BotsManager",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "BotsManager", targets: ["BotsManager"]),
        .executable(name: "bots-manager", targets: ["bots-manager"]),
    ],
    targets: [
        // Service logic: config, launchd, detached commands, docker compose, health checks.
        .target(name: "BotsCore"),
        // The menu bar app (SwiftUI MenuBarExtra).
        .executableTarget(name: "BotsManager", dependencies: ["BotsCore"]),
        // Small CLI to test the same logic from the shell.
        .executableTarget(name: "bots-manager", dependencies: ["BotsCore"]),
        .testTarget(name: "BotsCoreTests", dependencies: ["BotsCore"]),
    ]
)
