import SwiftUI

@main
struct BotsManagerApp: App {
    @State private var model = AppModel()

    var body: some Scene {
        MenuBarExtra {
            RootView(model: model)
        } label: {
            Image(systemName: model.menuIcon)
                .accessibilityLabel("Bots Manager")
        }
        .menuBarExtraStyle(.window)
    }
}
