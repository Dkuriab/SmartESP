import Foundation
import Testing
@testable import SmartEspKit

@Suite struct LaunchTests {
    @Test func windowOpensOnlyOnNormalLaunch() {
        #expect(opensWindowAtLaunch(arguments: ["/Applications/SmartEsp.app/Contents/MacOS/SmartEsp"], launchedAsLoginItem: false))
        #expect(!opensWindowAtLaunch(arguments: ["/x/SmartEsp"], launchedAsLoginItem: true))
        #expect(!opensWindowAtLaunch(arguments: ["/x/SmartEsp", "--background"], launchedAsLoginItem: false))
        #expect(!opensWindowAtLaunch(arguments: ["/x/SmartEsp", "--background"], launchedAsLoginItem: true))
    }

    @Test func secondInstanceHandsOffUnlessFirstIsQuitting() {
        #expect(secondInstanceAction(firstAnswer: .shown) == .handOff)
        // Старая версия или зависший первый экземпляр не ответил — как раньше, уступаем ему
        #expect(secondInstanceAction(firstAnswer: nil) == .handOff)
        #expect(secondInstanceAction(firstAnswer: .quitting) == .waitThenLaunch)
        #expect(SingleInstanceTiming.quitWait == 20)
        #expect(SingleInstanceTiming.replyWait < 5)
    }

    @Test func answerRoundTrip() {
        for answer in [SingleInstanceAnswer.shown, .quitting] {
            #expect(SingleInstanceAnswer(rawValue: answer.rawValue) == answer)
        }
    }
}
