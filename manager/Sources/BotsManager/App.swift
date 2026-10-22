import SwiftUI

@main
struct BotsManagerApp: App {
    @State private var model = AppModel()
    @State private var chat = ChatModel()

    var body: some Scene {
        MenuBarExtra {
            RootView(model: model)
        } label: {
            Image(systemName: model.menuIcon)
                .accessibilityLabel("Bots Manager")
        }
        .menuBarExtraStyle(.window)

        Window("Claude", id: "chat") {
            ChatView(chat: chat, model: model)
        }
        .defaultSize(width: 520, height: 640)
    }
}
