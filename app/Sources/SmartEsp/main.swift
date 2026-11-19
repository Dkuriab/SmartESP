import AppKit

// Второй экземпляр не запускает второе ядро: показывает окно первого и выходит
if SingleInstance.handOffToRunning() { exit(0) }

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
