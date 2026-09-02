import SwiftUI

@main
struct STLRepairApp: App {
    var body: some Scene {
        Window("Mac STL Repair", id: "main") {
            ContentView()
        }
        .windowResizability(.contentMinSize)
        .commands { CommandGroup(replacing: .newItem) {} }
    }
}
