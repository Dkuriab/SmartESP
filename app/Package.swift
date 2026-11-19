// swift-tools-version:6.0
import PackageDescription

let package = Package(
    name: "SmartEsp",
    platforms: [.macOS(.v14)],
    targets: [
        .target(name: "SmartEspKit"),
        .executableTarget(name: "SmartEsp", dependencies: ["SmartEspKit"]),
        .testTarget(name: "SmartEspKitTests", dependencies: ["SmartEspKit"]),
    ]
)
