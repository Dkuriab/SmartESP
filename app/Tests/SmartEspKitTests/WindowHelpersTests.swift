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
