import SwiftUI

@main
struct STLRepairApp: App {
    var body: some Scene {
        Window("STL Repair", id: "main") {
            ContentView()
        }
        .windowResizability(.contentMinSize)
        .commands { CommandGroup(replacing: .newItem) {} }
    }
}
