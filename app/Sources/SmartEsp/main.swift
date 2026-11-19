import AppKit
import SmartEspKit

// Пока пустой делегат: логика появится в следующих задачах.
final class AppDelegate: NSObject, NSApplicationDelegate {}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
