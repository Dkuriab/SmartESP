import Foundation
import Testing
@testable import SmartEspKit

@Suite struct WindowHelpersTests {
    @Test func retryOnlyOnNetworkErrors() {
        #expect(shouldRetryLoad(domain: NSURLErrorDomain, code: NSURLErrorCannotConnectToHost))
        #expect(!shouldRetryLoad(domain: NSURLErrorDomain, code: NSURLErrorCancelled))
        #expect(!shouldRetryLoad(domain: "WebKitErrorDomain", code: 102))
        #expect(!shouldRetryLoad(domain: "WKErrorDomain", code: 102))
    }
}

@Suite struct NavigationPolicyTests {
    private let core = URL(string: "http://127.0.0.1:8765/?token=x")!

    private func decide(_ text: String, core: URL? = nil) -> NavigationDecision {
        navigationDecision(for: URL(string: text), core: core)
    }

    @Test func coreOriginLoadsInWindow() {
        #expect(decide("http://127.0.0.1:8765/api/v1/status", core: core) == .allow)
        #expect(decide("http://localhost:8765/", core: core) == .allow)
        #expect(decide("HTTP://LOCALHOST:8765/", core: core) == .allow)
        #expect(decide("http://127.0.0.1:9999/") == .allow)  // ядро ещё не известно
        #expect(decide("about:blank", core: core) == .allow)
    }

    @Test func droppedFileAndOtherSchemesAreCancelled() {
        // брошенный на окно файл — переход на file://: интерфейс не должен смениться просмотром файла
        #expect(decide("file:///Users/me/Music/song.mp3", core: core) == .cancel)
        #expect(decide("blob:http://127.0.0.1:8765/abc", core: core) == .cancel)
        #expect(decide("data:text/html,hi", core: core) == .cancel)
        #expect(decide("javascript:alert(1)", core: core) == .cancel)
        #expect(navigationDecision(for: nil, core: core) == .cancel)
    }

    @Test func externalLinksGoToBrowser() {
        #expect(decide("https://example.com/", core: core) == .openExternally)
        #expect(decide("http://192.168.1.5:8765/", core: core) == .openExternally)
        #expect(decide("mailto:a@b.c", core: core) == .openExternally)
        #expect(decide("http://127.0.0.1:3000/", core: core) == .openExternally)  // другой порт — не ядро
    }

    @Test func ollamaLibraryLinkGoesToBrowser() {
        #expect(decide("https://ollama.com/library") == .openExternally)
        #expect(decide("http://127.0.0.1:8765/settings") == .allow)
    }
}
